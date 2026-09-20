"""Normalized PyDriller boundary for repository activity analysis.

PyDriller is intentionally kept behind this module.  The Activity analyzer
consumes the immutable facts defined here and never sees PyDriller's
``Repository``, ``Commit`` or ``ModifiedFile`` objects.  The collection method
is implemented as a streaming traversal in this same adapter so diffs,
patches, commit messages and source contents are never retained.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, Protocol, TypeAlias

import structlog

from ....ingestion.git_indexer.identity import author_identity_key
from .contracts import AnalyzerContext
from .process import workspace_root

log = structlog.get_logger("pydriller.adapter")

PYDRILLER_SOURCE_COMMIT = "a527c83ba81ee949cb84b977c155f337423743be"
PYDRILLER_VALIDATED_VERSION = "2.12"
PYDRILLER_POLICY_REVISION = "pydriller-2.12-policy-v2"
PYDRILLER_CONFIG_RELATIVE = Path("config/analyzers/pydriller.yaml")

RefScopeName: TypeAlias = Literal["default_branch", "all_local_refs", "all_refs_with_remotes"]


class PyDrillerExecutionStatus(StrEnum):
    """Source-level availability states, distinct from analyzer status."""

    MEASURED = "MEASURED"
    NO_ACTIVITY = "NO_ACTIVITY"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class FailureKind(StrEnum):
    """Stable adapter failure categories safe to expose in diagnostics."""

    MISSING_DEPENDENCY = "missing_dependency"
    MISSING_REPOSITORY = "missing_repository"
    INVALID_REPOSITORY = "invalid_repository"
    TIMEOUT = "timeout"
    TRAVERSAL_ERROR = "traversal_error"
    POLICY_ERROR = "policy_error"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _stable_tuple(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _bounded_float(value: object, *, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(minimum, min(maximum, number))


def _positive_int(value: object, *, default: int, minimum: int = 1) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, number)


@dataclass(frozen=True)
class RefPolicy:
    """Explicit Git reference and deduplication policy."""

    scope: RefScopeName = "default_branch"
    include_local_branches: bool = False
    include_remote_refs: bool = False
    include_tags: bool = False
    include_merge_commits: bool = True
    include_empty_commits: bool = True
    deduplicate_by: str = "commit_hash"
    commit_order: str = "date-order"

    def __post_init__(self) -> None:
        if self.scope not in {"default_branch", "all_local_refs", "all_refs_with_remotes"}:
            raise ValueError(f"unsupported PyDriller ref scope: {self.scope}")
        if self.deduplicate_by != "commit_hash":
            raise ValueError("PyDriller deduplication must use commit_hash")
        if self.commit_order != "date-order":
            raise ValueError("PyDriller traversal order must be date-order")
        if self.scope == "default_branch" and self.include_remote_refs:
            raise ValueError("default_branch scope cannot include remote refs")
        if self.scope == "all_refs_with_remotes" and not self.include_remote_refs:
            raise ValueError("all_refs_with_remotes requires include_remote_refs")


@dataclass(frozen=True)
class PyDrillerPolicy:
    """Validated repository-owned policy loaded from YAML."""

    policy_revision: str = PYDRILLER_POLICY_REVISION
    tool_version: str = PYDRILLER_VALIDATED_VERSION
    source_commit: str = PYDRILLER_SOURCE_COMMIT
    ref_policy: RefPolicy = field(default_factory=RefPolicy)
    window_days: tuple[int, ...] = (7, 30, 90, 365)
    bucket_days: int = 7
    low_change_churn_threshold: int = 5
    recent_commit_limit: int = 50
    file_history_limit: int = 2000
    max_unique_commits: int = 250_000
    max_tracked_contributors: int = 20_000
    sample_hash_limit: int = 20
    recency_weight: float = 0.55
    regularity_weight: float = 0.30
    meaningful_activity_weight: float = 0.15
    recency_half_life_days: float = 30.0
    pydriller_max_share: float = 0.25
    shallow_confidence_cap: float = 0.70
    truncated_confidence_cap: float = 0.60
    digest: str = ""

    def __post_init__(self) -> None:
        normalized_windows = tuple(sorted({int(day) for day in self.window_days if int(day) > 0}))
        if not normalized_windows:
            raise ValueError("PyDriller policy requires at least one positive window")
        object.__setattr__(self, "window_days", normalized_windows)
        score_total = self.recency_weight + self.regularity_weight + self.meaningful_activity_weight
        if score_total <= 0:
            raise ValueError("PyDriller score weights must have a positive total")
        object.__setattr__(self, "recency_weight", max(0.0, self.recency_weight) / score_total)
        object.__setattr__(self, "regularity_weight", max(0.0, self.regularity_weight) / score_total)
        object.__setattr__(self, "meaningful_activity_weight", max(0.0, self.meaningful_activity_weight) / score_total)
        object.__setattr__(self, "pydriller_max_share", _bounded_float(self.pydriller_max_share, default=0.25))
        object.__setattr__(self, "shallow_confidence_cap", _bounded_float(self.shallow_confidence_cap, default=0.70))
        object.__setattr__(self, "truncated_confidence_cap", _bounded_float(self.truncated_confidence_cap, default=0.60))

    def ref_policy_for_scope(self, scope: RefScopeName | None = None) -> RefPolicy:
        selected = scope or self.ref_policy.scope
        if selected == self.ref_policy.scope:
            return self.ref_policy
        if selected == "all_local_refs":
            return RefPolicy(
                scope=selected,
                include_local_branches=True,
                include_remote_refs=False,
                include_tags=False,
                include_merge_commits=self.ref_policy.include_merge_commits,
                include_empty_commits=self.ref_policy.include_empty_commits,
            )
        if selected == "all_refs_with_remotes":
            return RefPolicy(
                scope=selected,
                include_local_branches=True,
                include_remote_refs=True,
                include_tags=False,
                include_merge_commits=self.ref_policy.include_merge_commits,
                include_empty_commits=self.ref_policy.include_empty_commits,
            )
        return RefPolicy(
            scope="default_branch",
            include_local_branches=False,
            include_remote_refs=False,
            include_tags=False,
            include_merge_commits=self.ref_policy.include_merge_commits,
            include_empty_commits=self.ref_policy.include_empty_commits,
        )


@dataclass(frozen=True)
class ContributorFact:
    """Aggregated author/committer information without raw email addresses."""

    identity_key: str
    display_name: str | None
    author_commit_count: int
    committer_commit_count: int
    additions: int
    deletions: int
    churn: int
    first_activity_at: datetime | None
    last_activity_at: datetime | None
    is_bot_candidate: bool = False


@dataclass(frozen=True)
class FileHistoryFact:
    """Bounded per-file change history; no diff or source content."""

    path: str
    old_paths: tuple[str, ...] = ()
    commit_count: int = 0
    author_count: int = 0
    additions: int = 0
    deletions: int = 0
    churn: int = 0
    first_changed_at: datetime | None = None
    last_changed_at: datetime | None = None
    change_types: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class ActivityBucket:
    """Fixed-size time bucket used for deterministic dynamics/inactivity."""

    start_at: datetime
    end_at: datetime
    commit_count: int
    meaningful_commit_count: int
    churn: int
    author_count: int


@dataclass(frozen=True)
class ActivityWindow:
    """Commit/change aggregate for one configured lookback window."""

    days: int
    commit_count: int
    meaningful_commit_count: int
    author_count: int
    additions: int
    deletions: int
    churn: int
    merge_commit_count: int
    empty_commit_count: int


@dataclass(frozen=True)
class CommitSummary:
    """Bounded recent commit summary safe for analyzer evidence."""

    commit_hash: str
    author_identity_key: str
    committer_identity_key: str
    author_at: datetime | None
    committer_at: datetime | None
    changed_file_count: int
    additions: int
    deletions: int
    churn: int
    is_merge: bool
    is_empty: bool
    is_low_change: bool


@dataclass(frozen=True)
class GitActivityBaseline:
    """Optional existing Git/source facts used only for overlap diagnostics."""

    source: str
    commit_hashes: frozenset[str] | None = None
    unique_commit_count: int | None = None
    churn: int | None = None
    latest_activity_at: datetime | None = None


class RepositoryFactory(Protocol):
    """Testable factory for the PyDriller Repository API."""

    def __call__(self, path: str, **kwargs: Any) -> Any:
        ...


@dataclass(frozen=True)
class PyDrillerFacts:
    """Complete normalized result of one PyDriller traversal."""

    execution_status: PyDrillerExecutionStatus
    failure_kind: FailureKind | None = None
    failure_reason: str | None = None
    tool_name: str = "pydriller"
    tool_version: str = PYDRILLER_VALIDATED_VERSION
    source_commit: str = PYDRILLER_SOURCE_COMMIT
    policy_revision: str = PYDRILLER_POLICY_REVISION
    policy_digest: str = ""
    repository_head: str | None = None
    ref_scope: RefScopeName = "default_branch"
    resolved_refs: tuple[str, ...] = ()
    excluded_refs: tuple[str, ...] = ()
    history_is_shallow: bool = False
    history_complete: bool = True
    truncated: bool = False
    commit_occurrence_count: int = 0
    unique_commit_count: int = 0
    duplicate_commit_count: int = 0
    sample_commit_hashes: tuple[str, ...] = ()
    first_author_at: datetime | None = None
    last_author_at: datetime | None = None
    first_committer_at: datetime | None = None
    last_committer_at: datetime | None = None
    earliest_activity_at: datetime | None = None
    latest_activity_at: datetime | None = None
    recent_commits: tuple[CommitSummary, ...] = ()
    contributors: tuple[ContributorFact, ...] = ()
    unique_author_count: int = 0
    unique_committer_count: int = 0
    windows: tuple[ActivityWindow, ...] = ()
    buckets: tuple[ActivityBucket, ...] = ()
    modified_file_record_count: int = 0
    tracked_unique_file_count: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    total_churn: int = 0
    merge_commit_count: int = 0
    empty_commit_count: int = 0
    low_change_commit_count: int = 0
    change_types: tuple[tuple[str, int], ...] = ()
    file_histories: tuple[FileHistoryFact, ...] = ()
    file_history_truncated: bool = False
    current_inactivity_days: float | None = None
    longest_inactivity_days: float | None = None
    meaningful_activity_ratio: float | None = None
    contributor_concentration: float | None = None
    baseline_source: str | None = None
    overlap_commit_count: int | None = None
    new_commit_count: int | None = None
    overlap_status: Literal["measured", "unknown", "not_applicable"] = "not_applicable"
    double_count_guard: str = "pydriller_hash_deduplicated_not_added_to_source_counts"
    coverage: float = 0.0
    confidence: float = 0.0
    duration_ms: int = 0
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))
        object.__setattr__(self, "resolved_refs", _stable_tuple(self.resolved_refs))
        object.__setattr__(self, "excluded_refs", _stable_tuple(self.excluded_refs))
        object.__setattr__(self, "sample_commit_hashes", tuple(self.sample_commit_hashes))
        object.__setattr__(self, "coverage", _bounded_float(self.coverage, default=0.0))
        object.__setattr__(self, "confidence", _bounded_float(self.confidence, default=0.0))
        object.__setattr__(self, "duration_ms", max(0, int(self.duration_ms)))

    @property
    def has_activity(self) -> bool:
        return self.execution_status is PyDrillerExecutionStatus.MEASURED and self.unique_commit_count > 0

    @property
    def latest_activity_age_days(self) -> float | None:
        if self.latest_activity_at is None:
            return None
        reference = _as_utc(self.latest_activity_at)
        as_of = self.diagnostics.get("as_of_ts")
        if not isinstance(as_of, datetime) or reference is None:
            return None
        return max(0.0, (as_of.astimezone(UTC) - reference).total_seconds() / 86400.0)

    @property
    def active_period_count(self) -> int:
        """Number of configured buckets containing at least one commit."""
        return sum(1 for bucket in self.buckets if bucket.commit_count > 0)

    @property
    def observed_period_count(self) -> int:
        """Number of fixed buckets represented by the bounded history."""
        return len(self.buckets)

    def summary(self) -> dict[str, Any]:
        """Return a redacted, deterministic summary for diagnostics/evidence."""
        def iso(value: datetime | None) -> str | None:
            return value.isoformat() if isinstance(value, datetime) else None

        return {
            "execution_status": self.execution_status.value,
            "failure_kind": self.failure_kind.value if self.failure_kind else None,
            "tool_version": self.tool_version,
            "policy_revision": self.policy_revision,
            "ref_scope": self.ref_scope,
            "resolved_refs": self.resolved_refs,
            "history_is_shallow": self.history_is_shallow,
            "history_complete": self.history_complete,
            "truncated": self.truncated,
            "commit_occurrence_count": self.commit_occurrence_count,
            "unique_commit_count": self.unique_commit_count,
            "duplicate_commit_count": self.duplicate_commit_count,
            "unique_author_count": self.unique_author_count,
            "unique_committer_count": self.unique_committer_count,
            "first_author_at": iso(self.first_author_at),
            "last_author_at": iso(self.last_author_at),
            "first_committer_at": iso(self.first_committer_at),
            "last_committer_at": iso(self.last_committer_at),
            "earliest_activity_at": iso(self.earliest_activity_at),
            "latest_activity_at": iso(self.latest_activity_at),
            "modified_file_record_count": self.modified_file_record_count,
            "tracked_unique_file_count": self.tracked_unique_file_count,
            "total_additions": self.total_additions,
            "total_deletions": self.total_deletions,
            "total_churn": self.total_churn,
            "merge_commit_count": self.merge_commit_count,
            "empty_commit_count": self.empty_commit_count,
            "low_change_commit_count": self.low_change_commit_count,
            "overlap_status": self.overlap_status,
            "overlap_commit_count": self.overlap_commit_count,
            "new_commit_count": self.new_commit_count,
            "active_period_count": self.active_period_count,
            "observed_period_count": self.observed_period_count,
            "current_inactivity_days": self.current_inactivity_days,
            "longest_inactivity_days": self.longest_inactivity_days,
            "latest_activity_age_days": self.latest_activity_age_days,
            "meaningful_activity_ratio": self.meaningful_activity_ratio,
            "windows": tuple(
                {
                    "days": window.days,
                    "commit_count": window.commit_count,
                    "meaningful_commit_count": window.meaningful_commit_count,
                    "author_count": window.author_count,
                    "additions": window.additions,
                    "deletions": window.deletions,
                    "churn": window.churn,
                    "merge_commit_count": window.merge_commit_count,
                    "empty_commit_count": window.empty_commit_count,
                }
                for window in self.windows
            ),
            "coverage": self.coverage,
            "confidence": self.confidence,
        }


def _policy_mapping(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("PyDriller policy must be a YAML mapping")
    policy = raw.get("policy")
    if not isinstance(policy, Mapping):
        raise ValueError("PyDriller policy requires a policy mapping")
    analyzer = raw.get("analyzer")
    if not isinstance(analyzer, Mapping):
        raise ValueError("PyDriller policy requires an analyzer mapping")
    if str(analyzer.get("validated_pydriller_version")) != PYDRILLER_VALIDATED_VERSION:
        raise ValueError("PyDriller policy version does not match the validated package")
    if str(policy.get("policy_revision") or "") != PYDRILLER_POLICY_REVISION:
        raise ValueError("PyDriller policy revision does not match the adapter")
    return policy


def _ref_policy_from_mapping(policy: Mapping[str, Any]) -> RefPolicy:
    scope = str(policy.get("default_scope") or "default_branch")
    return RefPolicy(
        scope=scope,  # type: ignore[arg-type]
        include_local_branches=bool(policy.get("include_local_branches", False)),
        include_remote_refs=bool(policy.get("include_remote_refs", False)),
        include_tags=bool(policy.get("include_tags", False)),
        include_merge_commits=bool(policy.get("include_merge_commits", True)),
        include_empty_commits=bool(policy.get("include_empty_commits", True)),
        deduplicate_by=str(policy.get("deduplicate_by") or "commit_hash"),
        commit_order=str(policy.get("commit_order") or "date-order"),
    )


def load_pydriller_policy(root: Path | None = None) -> PyDrillerPolicy:
    """Load and validate the versioned repository-owned PyDriller policy."""
    import yaml

    resolved_root = Path(root or workspace_root()).resolve()
    policy_path = resolved_root / PYDRILLER_CONFIG_RELATIVE
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy = _policy_mapping(raw)
    windows = policy.get("windows")
    windows = windows if isinstance(windows, Mapping) else {}
    aggregation = policy.get("aggregation")
    aggregation = aggregation if isinstance(aggregation, Mapping) else {}
    score = policy.get("score")
    score = score if isinstance(score, Mapping) else {}
    digest = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    loaded = PyDrillerPolicy(
        policy_revision=str(policy.get("policy_revision") or PYDRILLER_POLICY_REVISION),
        ref_policy=_ref_policy_from_mapping(policy),
        window_days=tuple(int(item) for item in windows.get("days", (7, 30, 90, 365))),
        bucket_days=_positive_int(windows.get("bucket_days"), default=7),
        low_change_churn_threshold=_positive_int(aggregation.get("low_change_churn_threshold"), default=5, minimum=0),
        recent_commit_limit=_positive_int(aggregation.get("recent_commit_limit"), default=50),
        file_history_limit=_positive_int(aggregation.get("file_history_limit"), default=2000),
        max_unique_commits=_positive_int(aggregation.get("max_unique_commits"), default=250_000),
        max_tracked_contributors=_positive_int(aggregation.get("max_tracked_contributors"), default=20_000),
        sample_hash_limit=_positive_int(aggregation.get("sample_hash_limit"), default=20, minimum=0),
        recency_weight=float(score.get("recency_weight", 0.55)),
        regularity_weight=float(score.get("regularity_weight", 0.30)),
        meaningful_activity_weight=float(score.get("meaningful_activity_weight", 0.15)),
        recency_half_life_days=max(0.1, float(score.get("recency_half_life_days", 30.0))),
        pydriller_max_share=float(score.get("pydriller_max_share", 0.25)),
        shallow_confidence_cap=float(score.get("shallow_confidence_cap", 0.70)),
        truncated_confidence_cap=float(score.get("truncated_confidence_cap", 0.60)),
        digest=digest,
    )
    log.debug(
        "pydriller_policy_loaded",
        policy_revision=loaded.policy_revision,
        policy_digest=loaded.digest,
        ref_scope=loaded.ref_policy.scope,
        window_days=loaded.window_days,
    )
    return loaded


class _AdapterFailureError(RuntimeError):
    """Internal, already-classified adapter failure."""

    def __init__(
        self,
        status: PyDrillerExecutionStatus,
        failure_kind: FailureKind,
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.status = status
        self.failure_kind = failure_kind
        self.reason = reason


@dataclass
class _MutableContributor:
    display_names: set[str] = field(default_factory=set)
    author_commit_count: int = 0
    committer_commit_count: int = 0
    additions: int = 0
    deletions: int = 0
    first_activity_at: datetime | None = None
    last_activity_at: datetime | None = None


@dataclass
class _MutableFileHistory:
    old_paths: set[str] = field(default_factory=set)
    authors: set[str] = field(default_factory=set)
    commit_count: int = 0
    additions: int = 0
    deletions: int = 0
    first_changed_at: datetime | None = None
    last_changed_at: datetime | None = None
    change_types: Counter[str] = field(default_factory=Counter)


@dataclass
class _MutableWindow:
    commit_count: int = 0
    meaningful_commit_count: int = 0
    authors: set[str] = field(default_factory=set)
    additions: int = 0
    deletions: int = 0
    merge_commit_count: int = 0
    empty_commit_count: int = 0


@dataclass
class _MutableBucket:
    end_at: datetime
    commit_count: int = 0
    meaningful_commit_count: int = 0
    authors: set[str] = field(default_factory=set)
    churn: int = 0


@dataclass(frozen=True)
class _RepositoryMetadata:
    default_ref: str | None
    selected_refs: tuple[str, ...]
    excluded_refs: tuple[str, ...]
    excluded_ref_count: int
    shallow: bool


def _safe_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if value is None:
        return None
    try:
        return _as_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _safe_nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _actor_identity(actor: object) -> tuple[str, str | None]:
    name = str(getattr(actor, "name", "") or "").strip() or None
    email = str(getattr(actor, "email", "") or "").strip() or None
    raw_key = author_identity_key(name, email)
    if not raw_key:
        raw_key = "unknown"
    identity_key = f"identity:{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:20]}"
    return identity_key, name


def _normalize_path(value: object) -> str | None:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        return None
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        return None
    normalized = path.as_posix().lstrip("./")
    return normalized or None


def _change_type(value: object) -> str:
    name = getattr(value, "name", None)
    return str(name or value or "UNKNOWN").upper()


def _update_time_range(
    current_first: datetime | None,
    current_last: datetime | None,
    value: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    if value is None:
        return current_first, current_last
    first = value if current_first is None or value < current_first else current_first
    last = value if current_last is None or value > current_last else current_last
    return first, last


def _bucket_key(as_of: datetime, value: datetime | None, bucket_days: int, max_days: int) -> tuple[datetime, datetime] | None:
    if value is None or value > as_of:
        return None
    age_days = max(0.0, (as_of - value).total_seconds() / 86400.0)
    if age_days > max_days:
        return None
    index = int(age_days // bucket_days)
    end = as_of - timedelta(days=index * bucket_days)
    start = end - timedelta(days=bucket_days)
    return start, end


def _repository_ref_names(repository: Any) -> tuple[str, ...]:
    names: list[str] = []
    for head in getattr(repository, "heads", ()):
        name = str(getattr(head, "name", head) or "").strip()
        if name:
            names.append(name.removeprefix("refs/heads/"))
    for remote in getattr(repository, "remotes", ()):
        for ref in getattr(remote, "refs", ()):
            name = str(getattr(ref, "name", ref) or "").strip()
            if name and not name.endswith("/HEAD"):
                names.append(name.removeprefix("refs/remotes/"))
    for tag in getattr(repository, "tags", ()):
        name = str(getattr(tag, "name", tag) or "").strip()
        if name:
            names.append(f"tag:{name}")
    return tuple(sorted(set(names)))


def _default_ref(repository: Any, context: AnalyzerContext, heads: tuple[str, ...]) -> str | None:
    supplied = context.inventory.get("default_branch")
    if supplied:
        candidate = str(supplied).strip().removeprefix("refs/heads/")
        if candidate in heads:
            return candidate
    head = getattr(repository, "head", None)
    validity = getattr(head, "is_valid", None)
    head_is_valid = bool(validity()) if callable(validity) else bool(validity if validity is not None else True)
    if head is not None and head_is_valid and not bool(getattr(head, "is_detached", False)):
        reference = getattr(head, "reference", None)
        name = str(getattr(reference, "name", reference) or "").strip()
        if name:
            return name.removeprefix("refs/heads/")
    if heads:
        return heads[0]
    return None


def _repository_metadata(
    repo_path: Path,
    context: AnalyzerContext,
    policy: PyDrillerPolicy,
    ref_policy: RefPolicy,
    *,
    injected_repository: Any | None,
) -> _RepositoryMetadata:
    """Resolve refs without shelling out to Git."""
    if not repo_path.exists():
        raise _AdapterFailureError(
            PyDrillerExecutionStatus.UNAVAILABLE,
            FailureKind.MISSING_REPOSITORY,
            "local repository path is missing",
        )
    if not repo_path.is_dir():
        raise _AdapterFailureError(
            PyDrillerExecutionStatus.ERROR,
            FailureKind.INVALID_REPOSITORY,
            "local repository path is not a directory",
        )

    if injected_repository is not None:
        repository = injected_repository
    else:
        try:
            from git import Repo
            from git.exc import InvalidGitRepositoryError, NoSuchPathError
        except ImportError as exc:
            raise _AdapterFailureError(
                PyDrillerExecutionStatus.UNAVAILABLE,
                FailureKind.MISSING_DEPENDENCY,
                "GitPython is not installed",
            ) from exc
        try:
            repository = Repo(str(repo_path))
        except NoSuchPathError as exc:
            raise _AdapterFailureError(
                PyDrillerExecutionStatus.UNAVAILABLE,
                FailureKind.MISSING_REPOSITORY,
                "local repository path is missing",
            ) from exc
        except InvalidGitRepositoryError as exc:
            raise _AdapterFailureError(
                PyDrillerExecutionStatus.ERROR,
                FailureKind.INVALID_REPOSITORY,
                "path is not a valid Git repository",
            ) from exc
        if bool(getattr(repository, "bare", False)):
            raise _AdapterFailureError(
                PyDrillerExecutionStatus.ERROR,
                FailureKind.INVALID_REPOSITORY,
                "bare Git repositories are not supported for activity analysis",
            )

    all_refs = _repository_ref_names(repository)
    heads = tuple(
        sorted(
            {
                str(getattr(head, "name", head) or "").strip().removeprefix("refs/heads/")
                for head in getattr(repository, "heads", ())
                if str(getattr(head, "name", head) or "").strip()
            }
        )
    )
    default_ref = _default_ref(repository, context, heads)
    head = getattr(repository, "head", None)
    head_valid = True
    validity = getattr(head, "is_valid", None)
    if callable(validity):
        head_valid = bool(validity())
    elif validity is not None:
        head_valid = bool(validity)
    elif not heads:
        head_valid = False
    if ref_policy.scope == "default_branch":
        selected = (default_ref,) if default_ref else (("HEAD",) if head_valid else ())
    else:
        selected_list = list(heads) if ref_policy.include_local_branches else []
        if ref_policy.include_remote_refs:
            selected_list.extend(ref for ref in all_refs if "/" in ref and not ref.startswith("tag:"))
        if ref_policy.include_tags:
            selected_list.extend(ref for ref in all_refs if ref.startswith("tag:"))
        selected = tuple(sorted(set(selected_list)))
        if not selected and head_valid:
            selected = (default_ref or "HEAD",)
    selected_set = set(selected)
    excluded = tuple(ref for ref in all_refs if ref not in selected_set)
    shallow = False
    git_dir = getattr(repository, "git_dir", None)
    if git_dir:
        shallow = (Path(str(git_dir)) / "shallow").is_file()
    return _RepositoryMetadata(
        default_ref=default_ref,
        selected_refs=selected,
        excluded_refs=excluded[:100],
        excluded_ref_count=len(excluded),
        shallow=shallow,
    )


def _traverse(repository: Any) -> Iterable[Any]:
    traverse = getattr(repository, "traverse_commits", None)
    if callable(traverse):
        return traverse()
    if isinstance(repository, Iterable):
        return repository
    raise TypeError("PyDriller repository object has no traverse_commits method")


def _repository_kwargs(
    ref: str,
    context: AnalyzerContext,
    policy: PyDrillerPolicy,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "order": policy.ref_policy.commit_order,
        "include_refs": False,
        "include_remotes": False,
    }
    if ref.startswith("tag:"):
        kwargs["from_tag"] = ref.removeprefix("tag:")
    elif ref == "HEAD" or ref.startswith("HEAD:"):
        kwargs["to_commit"] = context.head_sha
    else:
        kwargs["only_in_branch"] = ref
    if policy.ref_policy.include_remote_refs and "/" in ref and not ref.startswith("tag:"):
        kwargs["include_remotes"] = True
    return kwargs


def _failure_facts(
    *,
    context: AnalyzerContext,
    policy: PyDrillerPolicy | None,
    status: PyDrillerExecutionStatus,
    failure_kind: FailureKind,
    reason: str,
    duration_ms: int,
) -> PyDrillerFacts:
    return PyDrillerFacts(
        execution_status=status,
        failure_kind=failure_kind,
        failure_reason=reason,
        tool_version=policy.tool_version if policy else PYDRILLER_VALIDATED_VERSION,
        source_commit=policy.source_commit if policy else PYDRILLER_SOURCE_COMMIT,
        policy_revision=policy.policy_revision if policy else PYDRILLER_POLICY_REVISION,
        policy_digest=policy.digest if policy else "",
        repository_head=context.head_sha,
        ref_scope=policy.ref_policy.scope if policy else "default_branch",
        history_complete=False,
        coverage=0.0,
        confidence=0.0,
        duration_ms=duration_ms,
        diagnostics={"as_of_ts": _as_utc(context.as_of_ts), "reason_category": reason},
    )


def _commit_modified_files(commit: Any) -> list[Any]:
    modified = getattr(commit, "modified_files", ())
    if modified is None:
        return []
    return list(modified)


def _build_facts(
    *,
    context: AnalyzerContext,
    policy: PyDrillerPolicy,
    metadata: _RepositoryMetadata,
    seen_hashes: set[str],
    commit_occurrences: int,
    duplicate_commits: int,
    contributors: dict[str, _MutableContributor],
    author_keys: set[str],
    committer_keys: set[str],
    windows: dict[int, _MutableWindow],
    buckets: dict[datetime, _MutableBucket],
    files: dict[str, _MutableFileHistory],
    change_types: Counter[str],
    recent_commits: list[CommitSummary],
    first_author: datetime | None,
    last_author: datetime | None,
    first_committer: datetime | None,
    last_committer: datetime | None,
    earliest_activity: datetime | None,
    latest_activity: datetime | None,
    modified_file_count: int,
    total_additions: int,
    total_deletions: int,
    total_churn: int,
    merge_count: int,
    empty_count: int,
    low_change_count: int,
    truncated: bool,
    file_history_truncated: bool,
    overlap: tuple[int | None, int | None, Literal["measured", "unknown", "not_applicable"]],
    duration_ms: int,
    diagnostics: Mapping[str, Any],
) -> PyDrillerFacts:
    as_of = _as_utc(context.as_of_ts) or datetime.now(UTC)
    max_window = max(policy.window_days)
    materialized_windows: list[ActivityWindow] = []
    for days in policy.window_days:
        window = windows[days]
        materialized_windows.append(
            ActivityWindow(
                days=days,
                commit_count=window.commit_count,
                meaningful_commit_count=window.meaningful_commit_count,
                author_count=len(window.authors),
                additions=window.additions,
                deletions=window.deletions,
                churn=window.additions + window.deletions,
                merge_commit_count=window.merge_commit_count,
                empty_commit_count=window.empty_commit_count,
            )
        )
    materialized_buckets = tuple(
        ActivityBucket(
            start_at=start,
            end_at=bucket.end_at,
            commit_count=bucket.commit_count,
            meaningful_commit_count=bucket.meaningful_commit_count,
            churn=bucket.churn,
            author_count=len(bucket.authors),
        )
        for start, bucket in sorted(buckets.items())
    )
    contributor_facts = tuple(
        ContributorFact(
            identity_key=identity,
            display_name=sorted(value.display_names)[0] if value.display_names else None,
            author_commit_count=value.author_commit_count,
            committer_commit_count=value.committer_commit_count,
            additions=value.additions,
            deletions=value.deletions,
            churn=value.additions + value.deletions,
            first_activity_at=value.first_activity_at,
            last_activity_at=value.last_activity_at,
        )
        for identity, value in sorted(contributors.items())
    )
    file_facts = tuple(
        FileHistoryFact(
            path=path,
            old_paths=tuple(sorted(value.old_paths)),
            commit_count=value.commit_count,
            author_count=len(value.authors),
            additions=value.additions,
            deletions=value.deletions,
            churn=value.additions + value.deletions,
            first_changed_at=value.first_changed_at,
            last_changed_at=value.last_changed_at,
            change_types=tuple(sorted(value.change_types.items())),
        )
        for path, value in sorted(files.items())
    )
    active_buckets = [bucket for bucket in materialized_buckets if bucket.commit_count]
    current_inactivity: float | None = None
    longest_inactivity: float | None = None
    if latest_activity is not None:
        current_inactivity = max(0.0, (as_of - latest_activity).total_seconds() / 86400.0)
    if active_buckets:
        gaps: list[float] = []
        for previous, current in pairwise(active_buckets):
            gaps.append(max(0.0, (current.start_at - previous.end_at).total_seconds() / 86400.0))
        longest_inactivity = max([current_inactivity or 0.0, *gaps])
    meaningful_ratio = (
        max(0, len(seen_hashes) - low_change_count)
        / max(1, len(seen_hashes))
        if seen_hashes
        else None
    )
    concentration = None
    if seen_hashes and contributors:
        concentration = max(
            value.author_commit_count for value in contributors.values()
        ) / len(seen_hashes)
    coverage = 1.0 if seen_hashes else 0.0
    confidence = coverage
    if metadata.shallow:
        coverage = min(coverage, policy.shallow_confidence_cap)
        confidence = min(confidence, policy.shallow_confidence_cap)
    if truncated or file_history_truncated:
        coverage = min(coverage, policy.truncated_confidence_cap)
        confidence = min(confidence, policy.truncated_confidence_cap)
    status = PyDrillerExecutionStatus.MEASURED if seen_hashes else PyDrillerExecutionStatus.NO_ACTIVITY
    return PyDrillerFacts(
        execution_status=status,
        tool_version=policy.tool_version,
        source_commit=policy.source_commit,
        policy_revision=policy.policy_revision,
        policy_digest=policy.digest,
        repository_head=context.head_sha,
        ref_scope=policy.ref_policy.scope,
        resolved_refs=metadata.selected_refs,
        excluded_refs=metadata.excluded_refs,
        history_is_shallow=metadata.shallow,
        history_complete=not metadata.shallow and not truncated,
        truncated=truncated,
        commit_occurrence_count=commit_occurrences,
        unique_commit_count=len(seen_hashes),
        duplicate_commit_count=duplicate_commits,
        sample_commit_hashes=tuple(sorted(seen_hashes)[: policy.sample_hash_limit]),
        first_author_at=first_author,
        last_author_at=last_author,
        first_committer_at=first_committer,
        last_committer_at=last_committer,
        earliest_activity_at=earliest_activity,
        latest_activity_at=latest_activity,
        recent_commits=tuple(sorted(recent_commits, key=lambda item: (item.committer_at or datetime.min.replace(tzinfo=UTC), item.commit_hash), reverse=True)),
        contributors=contributor_facts,
        unique_author_count=len(author_keys),
        unique_committer_count=len(committer_keys),
        windows=tuple(materialized_windows),
        buckets=materialized_buckets,
        modified_file_record_count=modified_file_count,
        tracked_unique_file_count=len(files),
        total_additions=total_additions,
        total_deletions=total_deletions,
        total_churn=total_churn,
        merge_commit_count=merge_count,
        empty_commit_count=empty_count,
        low_change_commit_count=low_change_count,
        change_types=tuple(sorted(change_types.items())),
        file_histories=file_facts,
        file_history_truncated=file_history_truncated,
        current_inactivity_days=current_inactivity,
        longest_inactivity_days=longest_inactivity,
        meaningful_activity_ratio=meaningful_ratio,
        contributor_concentration=concentration,
        baseline_source=overlap[2] if overlap[2] != "not_applicable" else None,
        overlap_commit_count=overlap[0],
        new_commit_count=overlap[1],
        overlap_status=overlap[2],
        coverage=coverage,
        confidence=confidence,
        duration_ms=duration_ms,
        diagnostics={**dict(diagnostics), "as_of_ts": as_of, "max_window_days": max_window},
    )


class PyDrillerAdapter:
    """Collect normalized Git-history facts through PyDriller's library API."""

    def __init__(
        self,
        *,
        repository_factory: RepositoryFactory | None = None,
        policy_loader: Any = load_pydriller_policy,
    ) -> None:
        self.repository_factory = repository_factory
        self.policy_loader = policy_loader

    def collect(
        self,
        context: AnalyzerContext,
        *,
        policy: PyDrillerPolicy | None = None,
        baseline: GitActivityBaseline | None = None,
    ) -> PyDrillerFacts:
        """Collect deterministic, bounded facts for ``context``."""
        started = time.perf_counter()
        loaded_policy = policy
        try:
            loaded_policy = loaded_policy or self.policy_loader()
        except (OSError, TypeError, ValueError) as exc:
            log.error(
                "pydriller_policy_failed",
                repo_id=context.repo_id,
                status=PyDrillerExecutionStatus.ERROR.value,
                failure_kind=FailureKind.POLICY_ERROR.value,
                error_type=type(exc).__name__,
            )
            return _failure_facts(
                context=context,
                policy=loaded_policy,
                status=PyDrillerExecutionStatus.ERROR,
                failure_kind=FailureKind.POLICY_ERROR,
                reason="PyDriller policy could not be loaded",
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )

        requested_scope = context.inventory.get("pydriller_scope")
        try:
            scope = str(requested_scope or loaded_policy.ref_policy.scope)
            ref_policy = loaded_policy.ref_policy_for_scope(scope)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            log.error(
                "pydriller_scope_failed",
                repo_id=context.repo_id,
                status=PyDrillerExecutionStatus.ERROR.value,
                failure_kind=FailureKind.POLICY_ERROR.value,
                error_type=type(exc).__name__,
            )
            return _failure_facts(
                context=context,
                policy=loaded_policy,
                status=PyDrillerExecutionStatus.ERROR,
                failure_kind=FailureKind.POLICY_ERROR,
                reason="unsupported PyDriller ref scope",
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
        effective_policy = PyDrillerPolicy(
            policy_revision=loaded_policy.policy_revision,
            tool_version=loaded_policy.tool_version,
            source_commit=loaded_policy.source_commit,
            ref_policy=ref_policy,
            window_days=loaded_policy.window_days,
            bucket_days=loaded_policy.bucket_days,
            low_change_churn_threshold=loaded_policy.low_change_churn_threshold,
            recent_commit_limit=loaded_policy.recent_commit_limit,
            file_history_limit=loaded_policy.file_history_limit,
            max_unique_commits=loaded_policy.max_unique_commits,
            max_tracked_contributors=loaded_policy.max_tracked_contributors,
            sample_hash_limit=loaded_policy.sample_hash_limit,
            recency_weight=loaded_policy.recency_weight,
            regularity_weight=loaded_policy.regularity_weight,
            meaningful_activity_weight=loaded_policy.meaningful_activity_weight,
            recency_half_life_days=loaded_policy.recency_half_life_days,
            pydriller_max_share=loaded_policy.pydriller_max_share,
            shallow_confidence_cap=loaded_policy.shallow_confidence_cap,
            truncated_confidence_cap=loaded_policy.truncated_confidence_cap,
            digest=loaded_policy.digest,
        )
        try:
            from pydriller import Repository
        except (ImportError, ModuleNotFoundError):
            log.warning(
                "pydriller_unavailable",
                repo_id=context.repo_id,
                status=PyDrillerExecutionStatus.UNAVAILABLE.value,
                failure_kind=FailureKind.MISSING_DEPENDENCY.value,
            )
            return _failure_facts(
                context=context,
                policy=effective_policy,
                status=PyDrillerExecutionStatus.UNAVAILABLE,
                failure_kind=FailureKind.MISSING_DEPENDENCY,
                reason="PyDriller is not installed",
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )

        try:
            repo_path = Path(context.repo_path).resolve()
            metadata = _repository_metadata(
                repo_path,
                context,
                effective_policy,
                ref_policy,
                injected_repository=None,
            )
            factory = self.repository_factory or Repository
            seen_hashes: set[str] = set()
            commit_occurrences = 0
            duplicate_commits = 0
            contributors: dict[str, _MutableContributor] = defaultdict(_MutableContributor)
            author_keys: set[str] = set()
            committer_keys: set[str] = set()
            windows = {days: _MutableWindow() for days in effective_policy.window_days}
            buckets: dict[datetime, _MutableBucket] = {}
            files: dict[str, _MutableFileHistory] = {}
            change_types: Counter[str] = Counter()
            recent_commits: list[CommitSummary] = []
            first_author = last_author = None
            first_committer = last_committer = None
            earliest_activity = latest_activity = None
            modified_file_count = total_additions = total_deletions = total_churn = 0
            merge_count = empty_count = low_change_count = 0
            truncated = False
            file_history_truncated = False
            excluded_empty_count = 0
            future_commit_count = 0
            shallow_modification_error_count = 0
            as_of = _as_utc(context.as_of_ts) or datetime.now(UTC)
            max_window = max(effective_policy.window_days)

            for ref in metadata.selected_refs:
                repository = factory(str(repo_path), **_repository_kwargs(ref, context, effective_policy))
                for commit in _traverse(repository):
                    commit_occurrences += 1
                    commit_hash = str(getattr(commit, "hash", "") or "").strip()
                    if not commit_hash:
                        raise ValueError("PyDriller commit has no hash")
                    if commit_hash in seen_hashes:
                        duplicate_commits += 1
                        continue
                    if len(seen_hashes) >= effective_policy.max_unique_commits:
                        truncated = True
                        break
                    seen_hashes.add(commit_hash)
                    author_at = _safe_datetime(getattr(commit, "author_date", None))
                    committer_at = _safe_datetime(getattr(commit, "committer_date", None))
                    activity_at = committer_at or author_at
                    if activity_at is not None and activity_at > as_of:
                        future_commit_count += 1
                    author_key, author_name = _actor_identity(getattr(commit, "author", None))
                    committer_key, committer_name = _actor_identity(getattr(commit, "committer", None))
                    author_keys.add(author_key)
                    committer_keys.add(committer_key)
                    modifications_unavailable = False
                    try:
                        modifications = _commit_modified_files(commit)
                    except Exception as exc:
                        if not metadata.shallow:
                            raise
                        modifications = []
                        modifications_unavailable = True
                        shallow_modification_error_count += 1
                        file_history_truncated = True
                        log.warning(
                            "pydriller_shallow_modifications_unavailable",
                            repo_id=context.repo_id,
                            error_type=type(exc).__name__,
                        )
                    merge = bool(getattr(commit, "merge", False))
                    is_empty = not modifications and not modifications_unavailable and not merge
                    if is_empty and not effective_policy.ref_policy.include_empty_commits:
                        excluded_empty_count += 1
                        continue
                    if merge:
                        merge_count += 1
                    if is_empty:
                        empty_count += 1
                    commit_additions = 0
                    commit_deletions = 0
                    commit_change_types: Counter[str] = Counter()
                    for modification in modifications:
                        new_path = _normalize_path(getattr(modification, "new_path", None))
                        old_path = _normalize_path(getattr(modification, "old_path", None))
                        path = new_path or old_path
                        added = _safe_nonnegative_int(getattr(modification, "added_lines", 0))
                        deleted = _safe_nonnegative_int(getattr(modification, "deleted_lines", 0))
                        change = _change_type(getattr(modification, "change_type", None))
                        commit_additions += added
                        commit_deletions += deleted
                        commit_change_types[change] += 1
                        change_types[change] += 1
                        modified_file_count += 1
                        if path is None:
                            continue
                        if path not in files and len(files) >= effective_policy.file_history_limit:
                            file_history_truncated = True
                            continue
                        history = files.setdefault(path, _MutableFileHistory())
                        if old_path and old_path != path:
                            history.old_paths.add(old_path)
                        history.authors.add(author_key)
                        history.commit_count += 1
                        history.additions += added
                        history.deletions += deleted
                        history.first_changed_at, history.last_changed_at = _update_time_range(
                            history.first_changed_at,
                            history.last_changed_at,
                            activity_at,
                        )
                        history.change_types[change] += 1
                    commit_churn = commit_additions + commit_deletions
                    low_change = (
                        not modifications_unavailable
                        and not merge
                        and commit_churn <= effective_policy.low_change_churn_threshold
                    )
                    meaningful = modifications_unavailable or (not is_empty and not low_change)
                    if low_change:
                        low_change_count += 1
                    total_additions += commit_additions
                    total_deletions += commit_deletions
                    total_churn += commit_churn
                    first_author, last_author = _update_time_range(first_author, last_author, author_at)
                    first_committer, last_committer = _update_time_range(first_committer, last_committer, committer_at)
                    if activity_at is not None and activity_at <= as_of:
                        earliest_activity, latest_activity = _update_time_range(earliest_activity, latest_activity, activity_at)
                    contributor_roles = (
                        (author_key, author_name, True),
                        (committer_key, committer_name, False),
                    )
                    updated_contributors: set[str] = set()
                    for identity, name, is_author in contributor_roles:
                        if len(contributors) >= effective_policy.max_tracked_contributors and identity not in contributors:
                            continue
                        person = contributors[identity]
                        if name:
                            person.display_names.add(name)
                        if is_author:
                            person.author_commit_count += 1
                        else:
                            person.committer_commit_count += 1
                        if identity not in updated_contributors:
                            person.additions += commit_additions
                            person.deletions += commit_deletions
                            person.first_activity_at, person.last_activity_at = _update_time_range(
                                person.first_activity_at,
                                person.last_activity_at,
                                activity_at,
                            )
                            updated_contributors.add(identity)
                    for days, window in windows.items():
                        if activity_at is None or activity_at > as_of or activity_at < as_of - timedelta(days=days):
                            continue
                        window.commit_count += 1
                        window.meaningful_commit_count += int(meaningful)
                        window.authors.add(author_key)
                        window.additions += commit_additions
                        window.deletions += commit_deletions
                        window.merge_commit_count += int(merge)
                        window.empty_commit_count += int(is_empty)
                    bucket = _bucket_key(as_of, activity_at, effective_policy.bucket_days, max_window)
                    if bucket is not None:
                        start, end = bucket
                        state = buckets.setdefault(start, _MutableBucket(end_at=end))
                        state.commit_count += 1
                        state.meaningful_commit_count += int(meaningful)
                        state.authors.add(author_key)
                        state.churn += commit_churn
                    recent_commits.append(
                        CommitSummary(
                            commit_hash=commit_hash,
                            author_identity_key=author_key,
                            committer_identity_key=committer_key,
                            author_at=author_at,
                            committer_at=committer_at,
                            changed_file_count=len(modifications),
                            additions=commit_additions,
                            deletions=commit_deletions,
                            churn=commit_churn,
                            is_merge=merge,
                            is_empty=is_empty,
                            is_low_change=low_change,
                        )
                    )
                    if len(recent_commits) > effective_policy.recent_commit_limit * 2:
                        recent_commits[:] = sorted(
                            recent_commits,
                            key=lambda item: (item.committer_at or datetime.min.replace(tzinfo=UTC), item.commit_hash),
                            reverse=True,
                        )[: effective_policy.recent_commit_limit]
                if truncated:
                    break

            overlap_status: Literal["measured", "unknown", "not_applicable"] = "not_applicable"
            overlap_count: int | None = None
            new_count: int | None = None
            if baseline is not None:
                if baseline.commit_hashes is not None:
                    overlap_count = len(seen_hashes.intersection(baseline.commit_hashes))
                    new_count = len(seen_hashes.difference(baseline.commit_hashes))
                    overlap_status = "measured"
                else:
                    overlap_status = "unknown"
            diagnostics = {
                "as_of_ts": as_of,
                "selected_ref_count": len(metadata.selected_refs),
                "excluded_ref_count": metadata.excluded_ref_count,
                "excluded_empty_commit_count": excluded_empty_count,
                "future_commit_count": future_commit_count,
                "shallow_modification_error_count": shallow_modification_error_count,
                "max_unique_commits": effective_policy.max_unique_commits,
                "max_tracked_contributors": effective_policy.max_tracked_contributors,
                "double_count_guard": "commit_hash_set",
                "bucket_days": effective_policy.bucket_days,
            }
            facts = _build_facts(
                context=context,
                policy=effective_policy,
                metadata=metadata,
                seen_hashes=seen_hashes,
                commit_occurrences=commit_occurrences,
                duplicate_commits=duplicate_commits,
                contributors=contributors,
                author_keys=author_keys,
                committer_keys=committer_keys,
                windows=windows,
                buckets=buckets,
                files=files,
                change_types=change_types,
                recent_commits=recent_commits,
                first_author=first_author,
                last_author=last_author,
                first_committer=first_committer,
                last_committer=last_committer,
                earliest_activity=earliest_activity,
                latest_activity=latest_activity,
                modified_file_count=modified_file_count,
                total_additions=total_additions,
                total_deletions=total_deletions,
                total_churn=total_churn,
                merge_count=merge_count,
                empty_count=empty_count,
                low_change_count=low_change_count,
                truncated=truncated,
                file_history_truncated=file_history_truncated,
                overlap=(overlap_count, new_count, overlap_status),
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                diagnostics=diagnostics,
            )
            if baseline is not None:
                facts = replace(facts, baseline_source=baseline.source)
            log.info(
                "pydriller_collection_finished",
                repo_id=context.repo_id,
                status=facts.execution_status.value,
                ref_scope=facts.ref_scope,
                selected_ref_count=len(facts.resolved_refs),
                unique_commits=facts.unique_commit_count,
                duplicate_commits=facts.duplicate_commit_count,
                total_churn=facts.total_churn,
                shallow=facts.history_is_shallow,
                truncated=facts.truncated,
                duration_ms=facts.duration_ms,
            )
            return facts
        except _AdapterFailureError as exc:
            log.warning(
                "pydriller_collection_unavailable",
                repo_id=context.repo_id,
                status=exc.status.value,
                failure_kind=exc.failure_kind.value,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
            return _failure_facts(
                context=context,
                policy=effective_policy,
                status=exc.status,
                failure_kind=exc.failure_kind,
                reason=exc.reason,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
        except TimeoutError:
            log.warning(
                "pydriller_collection_timeout",
                repo_id=context.repo_id,
                status=PyDrillerExecutionStatus.ERROR.value,
                failure_kind=FailureKind.TIMEOUT.value,
            )
            return _failure_facts(
                context=context,
                policy=effective_policy,
                status=PyDrillerExecutionStatus.ERROR,
                failure_kind=FailureKind.TIMEOUT,
                reason="PyDriller traversal timed out",
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )
        except Exception as exc:
            log.error(
                "pydriller_collection_failed",
                repo_id=context.repo_id,
                status=PyDrillerExecutionStatus.ERROR.value,
                failure_kind=FailureKind.TRAVERSAL_ERROR.value,
                error_type=type(exc).__name__,
            )
            return _failure_facts(
                context=context,
                policy=effective_policy,
                status=PyDrillerExecutionStatus.ERROR,
                failure_kind=FailureKind.TRAVERSAL_ERROR,
                reason="PyDriller traversal failed",
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
            )


__all__ = [
    "PYDRILLER_CONFIG_RELATIVE",
    "PYDRILLER_POLICY_REVISION",
    "PYDRILLER_SOURCE_COMMIT",
    "PYDRILLER_VALIDATED_VERSION",
    "ActivityBucket",
    "ActivityWindow",
    "CommitSummary",
    "ContributorFact",
    "FailureKind",
    "FileHistoryFact",
    "GitActivityBaseline",
    "PyDrillerAdapter",
    "PyDrillerExecutionStatus",
    "PyDrillerFacts",
    "PyDrillerPolicy",
    "RefPolicy",
    "RepositoryFactory",
    "load_pydriller_policy",
]
