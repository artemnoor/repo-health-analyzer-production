"""Collector-owned compatibility wrappers for the proven health adapters.

The wrappers are deliberately an anti-corruption layer. Existing adapters keep
their validated policy and live transport behavior, while this module exposes
only bounded scalar observations and source status through ``RepositoryFacts``.
The existing analyzer path remains callable until its parity migration is
completed in a later phase.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext, AnalyzerResult
from repowise.core.analysis.health.integrations.appsec_adapter import (
    AppSecTransport,
    SourceCraftAppSecAdapter,
)
from repowise.core.analysis.health.integrations.cicd_adapter import SourceCraftCICDAdapter
from repowise.core.analysis.health.integrations.cicd_facts import CICDPolicy, load_cicd_policy
from repowise.core.analysis.health.integrations.code_health_collector import (
    CodeHealthFactsCollector,
)
from repowise.core.analysis.health.integrations.code_health_facts import (
    CodeHealthFacts as LegacyCodeHealthFacts,
)
from repowise.core.analysis.health.integrations.issues_facts import (
    IssuesPolicy,
    load_issues_policy,
    normalize_issue_inventory,
)
from repowise.core.analysis.health.integrations.pydriller_adapter import (
    PyDrillerAdapter,
    PyDrillerFacts,
    PyDrillerPolicy,
)
from repowise.core.analysis.health.integrations.vale_adapter import ValeAdapter

from ..contracts.requests import RepositoryRef
from ..contracts.results import (
    CicdFacts,
    CollectionState,
    DocumentationFacts,
    FactGroup,
    FactObservation,
    GitFacts,
    IssuesFacts,
    Limitation,
    RepositoryFacts,
    SecurityFacts,
    SourceStatus,
)
from ..contracts.results import (
    CodeHealthFacts as NormalizedCodeHealthFacts,
)
from .ports import CollectionContext

_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|/|\\\\)")
_SECRET_MARKERS = ("api_key", "apikey", "authorization", "bearer", "password", "secret", "token")


def _legacy_context(
    repository: RepositoryRef,
    context: CollectionContext,
    *,
    inventory: Mapping[str, Any] | None = None,
) -> AnalyzerContext:
    values = dict(inventory or {})
    values.setdefault("repository_id", repository.repository_id)
    values.setdefault("sourcecraft_repository_id", repository.repository_id)
    return AnalyzerContext(
        repo_path=context.checkout_path,
        repo_id=repository.repository_id,
        head_sha=repository.head_sha or "unknown",
        as_of_ts=context.request.as_of,
        mode=context.request.mode,
        inventory=values,
        config_digest=context.request.config_digest,
        time_budget=context.request.timeout_seconds,
    )


def _status(value: object) -> CollectionState:
    normalized = str(getattr(value, "value", value) or "").strip().upper()
    if normalized in {"MEASURED", "AVAILABLE", "NO_ACTIVITY", "PASS", "WARN", "FAIL"}:
        return CollectionState.AVAILABLE
    if normalized == "NOT_APPLICABLE":
        return CollectionState.UNAVAILABLE
    if normalized in {"INCONCLUSIVE", "DEGRADED"}:
        return CollectionState.PARTIAL
    if normalized in {"PARTIAL", "DEGRADED"}:
        return CollectionState.PARTIAL
    if normalized in {"UNAVAILABLE", "MISSING", "MISSING_DEPENDENCY"}:
        return CollectionState.UNAVAILABLE
    if normalized in {"TIMEOUT", "TIMED_OUT"}:
        return CollectionState.TIMEOUT
    if normalized in {"PERMISSION_DENIED", "FORBIDDEN", "UNAUTHORIZED"}:
        return CollectionState.PERMISSION_DENIED
    return CollectionState.ERROR


def _limitation(value: object) -> Limitation:
    text = str(value or "unspecified collection limitation").strip()[:1000]
    code = re.sub(r"[^a-z0-9_.-]+", "_", text.casefold()).strip("._-")[:128] or "collection_limited"
    return Limitation(code=code, reason=text)


def _safe_scalar(value: object) -> bool | int | float | str | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        normalized = value.strip()
        if any(marker in normalized.casefold() for marker in _SECRET_MARKERS):
            return "[redacted]"
        if _ABSOLUTE_PATH_RE.match(normalized):
            return "[redacted-path]"
        return normalized[:512]
    return None


def _observations(summary: Mapping[str, Any]) -> tuple[FactObservation, ...]:
    result: list[FactObservation] = []
    for key, raw_value in sorted(summary.items(), key=lambda item: str(item[0])):
        if isinstance(raw_value, (Mapping, Sequence)) and not isinstance(
            raw_value, (str, bytes, bytearray)
        ):
            continue
        value = _safe_scalar(raw_value)
        if value is None and raw_value is not None:
            continue
        normalized_key = re.sub(r"[^a-z0-9_.-]+", "_", str(key).casefold()).strip("._-")[:128]
        if not normalized_key:
            continue
        result.append(FactObservation(key=normalized_key, value=value))
    return tuple(result)


def _to_repository_facts(
    repository: RepositoryRef,
    *,
    source_id: str,
    source_version: str | None,
    state: CollectionState,
    coverage: float = 0.0,
    confidence: float = 0.0,
    summary: Mapping[str, Any],
    group_type: type[FactGroup],
    collected_at: datetime,
    limitations: Sequence[object] = (),
) -> RepositoryFacts:
    normalized_limitations = tuple(
        _limitation(item) for item in limitations if item not in (None, "")
    )
    if state not in {CollectionState.AVAILABLE, CollectionState.PARTIAL}:
        normalized_limitations += (_limitation(summary.get("failure_kind") or state.value),)
    group = group_type(
        available=state in {CollectionState.AVAILABLE, CollectionState.PARTIAL},
        observations=(
            *(_observations(summary)),
            FactObservation(key="coverage", value=max(0.0, min(1.0, coverage))),
            FactObservation(key="confidence", value=max(0.0, min(1.0, confidence))),
        ),
        limitations=normalized_limitations,
    )
    facts = RepositoryFacts(
        repository=repository,
        source_snapshot_digest=None,
        collected_at=collected_at.astimezone(UTC),
        source_versions={source_id: source_version or "unknown"},
        source_statuses=(
            SourceStatus(
                source_id=source_id,
                state=state,
                source_version=source_version,
                snapshot_digest=None,
                collected_at=collected_at.astimezone(UTC),
                limitations=normalized_limitations,
            ),
        ),
        limitations=normalized_limitations,
        **{_group_field(group_type): group},
    )
    source_snapshot_digest = facts.digest()
    statuses = tuple(
        status.model_copy(update={"snapshot_digest": source_snapshot_digest})
        for status in facts.source_statuses
    )
    return facts.model_copy(
        update={
            "source_snapshot_digest": source_snapshot_digest,
            "source_statuses": statuses,
        }
    )


def _group_field(group_type: type[FactGroup]) -> str:
    return {
        SecurityFacts: "security",
        IssuesFacts: "issues",
        CicdFacts: "cicd",
        DocumentationFacts: "documentation",
        GitFacts: "git",
        NormalizedCodeHealthFacts: "code_health",
    }[group_type]


class SourceCraftAppSecCollector:
    source_id = "sourcecraft.appsec"
    provider = "sourcecraft"

    def __init__(
        self,
        transport: AppSecTransport | None = None,
        *,
        inventory: Mapping[str, Any] | None = None,
    ) -> None:
        self.adapter = SourceCraftAppSecAdapter(transport=transport)
        self.inventory = dict(inventory or {})

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        facts = self.adapter.collect(_legacy_context(repository, context, inventory=self.inventory))
        return _to_repository_facts(
            repository,
            source_id=self.source_id,
            source_version=facts.source_version,
            state=_status(facts.status),
            coverage=facts.coverage,
            confidence=facts.confidence,
            summary=facts.summary(),
            group_type=SecurityFacts,
            collected_at=context.request.as_of,
            limitations=(facts.failure_kind,) if facts.failure_kind else (),
        )


class SourceCraftIssuesCollector:
    source_id = "sourcecraft.issues"
    provider = "sourcecraft"

    def __init__(
        self,
        *,
        inventory: Mapping[str, Any] | None = None,
        policy: IssuesPolicy | None = None,
    ) -> None:
        self.inventory = dict(inventory or {})
        self.policy = policy

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        legacy = _legacy_context(repository, context, inventory=self.inventory)
        policy = self.policy or load_issues_policy(context.checkout_path)
        facts = normalize_issue_inventory(legacy, policy)
        summary = facts.summary()
        return _to_repository_facts(
            repository,
            source_id=self.source_id,
            source_version=facts.source_version,
            state=_status(facts.status),
            coverage=facts.coverage,
            confidence=facts.confidence,
            summary=summary,
            group_type=IssuesFacts,
            collected_at=facts.as_of,
            limitations=facts.limitations,
        )


class SourceCraftCicdCollector:
    source_id = "sourcecraft.cicd"
    provider = "sourcecraft"

    def __init__(
        self,
        *,
        inventory: Mapping[str, Any] | None = None,
        policy: CICDPolicy | None = None,
        adapter: SourceCraftCICDAdapter | None = None,
    ) -> None:
        self.inventory = dict(inventory or {})
        self.policy = policy
        self.adapter = adapter or SourceCraftCICDAdapter()

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        legacy = _legacy_context(repository, context, inventory=self.inventory)
        policy = self.policy or load_cicd_policy(context.checkout_path)
        facts = self.adapter.collect(legacy, policy=policy)
        return _to_repository_facts(
            repository,
            source_id=self.source_id,
            source_version=facts.source_version,
            state=_status(facts.status),
            coverage=facts.coverage,
            confidence=facts.confidence,
            summary=facts.summary(),
            group_type=CicdFacts,
            collected_at=facts.as_of_at,
            limitations=facts.limitations,
        )


class PyDrillerActivityCollector:
    source_id = "git.pydriller"

    def __init__(
        self, adapter: PyDrillerAdapter | None = None, *, policy: PyDrillerPolicy | None = None
    ) -> None:
        self.adapter = adapter or PyDrillerAdapter()
        self.policy = policy

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        facts: PyDrillerFacts = self.adapter.collect(
            _legacy_context(repository, context),
            policy=self.policy,
        )
        return _to_repository_facts(
            repository,
            source_id=self.source_id,
            source_version=facts.tool_version,
            state=_status(facts.execution_status),
            coverage=facts.coverage,
            confidence=facts.confidence,
            summary=facts.summary(),
            group_type=GitFacts,
            collected_at=context.request.as_of,
            limitations=(facts.failure_reason,) if facts.failure_reason else (),
        )


class ValeDocumentationCollector:
    source_id = "vale.documentation"

    def __init__(self, adapter: ValeAdapter | None = None) -> None:
        self.adapter = adapter or ValeAdapter()

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        result: AnalyzerResult = self.adapter.run(_legacy_context(repository, context))
        summary = {
            "status": result.status.value,
            "score": result.score,
            "metric_count": len(result.metrics),
            "finding_count": len(result.findings),
            "evidence_count": len(result.evidence),
            "limitation_count": len(result.limitations),
        }
        return _to_repository_facts(
            repository,
            source_id=self.source_id,
            source_version=result.analyzer_version,
            state=_status(result.status),
            coverage=1.0 if result.total_weight > 0 else 0.0,
            confidence=1.0 if result.total_weight > 0 else 0.0,
            summary=summary,
            group_type=DocumentationFacts,
            collected_at=context.request.as_of,
            limitations=tuple(item.reason for item in result.limitations),
        )


class CodeHealthCollector:
    source_id = "repowise.code-health"

    def __init__(self, collector: CodeHealthFactsCollector | None = None) -> None:
        self.collector = collector or CodeHealthFactsCollector()

    def collect(self, repository: RepositoryRef, *, context: CollectionContext) -> RepositoryFacts:
        facts: LegacyCodeHealthFacts = self.collector.collect(_legacy_context(repository, context))
        summary = facts.summary()
        return _to_repository_facts(
            repository,
            source_id=self.source_id,
            source_version=facts.policy_revision,
            state=_status(facts.status),
            coverage=facts.coverage,
            confidence=facts.confidence,
            summary=summary,
            group_type=NormalizedCodeHealthFacts,
            collected_at=facts.as_of_at,
            limitations=facts.limitations,
        )


__all__ = [
    "CodeHealthCollector",
    "PyDrillerActivityCollector",
    "SourceCraftAppSecCollector",
    "SourceCraftCicdCollector",
    "SourceCraftIssuesCollector",
    "ValeDocumentationCollector",
]
