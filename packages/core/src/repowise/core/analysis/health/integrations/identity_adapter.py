"""Contributor identity enrichment backed by the copied CHAOSS blocks.

CollectOSS and SortingHat already define the durable contributor, alias,
affiliation and recommendation shapes.  This module keeps those packages as
the source of truth and adds only the RepoWise envelope, confidence policy and
immutable replay view needed by the local analyzer.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from repowise.core.ingestion.git_indexer.identity import (
    author_identity_key,
    canonicalize_author_email,
)

from .contracts import (
    AnalyzerContext,
    AnalyzerDefinition,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
    Finding,
    Limitation,
    MetricValue,
)
from .forge_adapter import RawFact
from .process import workspace_root

log = structlog.get_logger("identity.resolve")

COLLECTOSS_COMMIT = "339edc520e79dd1728ca19255d94a05a4a107df1"
SORTINGHAT_COMMIT = "2048a9cfb15b21da7c45082c3966a3462ce51826"
IDENTITY_MAPPING_VERSION = "repowise-identity-v1"
IDENTITY_ANALYZER_ID = "identity.enrichment"
IDENTITY_DEFINITION = AnalyzerDefinition(
    id=IDENTITY_ANALYZER_ID,
    version=IDENTITY_MAPPING_VERSION,
    category="identity-enrichment",
    dimensions=("community", "contributors", "ownership"),
    requires=("chaoss:events",),
    phase=70,
    cost=25,
    timeout=45,
    cache_policy="read_write",
    source_commit=SORTINGHAT_COMMIT,
    enabled_by_mode=("full", "fast", "offline", "diff", "backfill"),
)


@dataclass(frozen=True)
class IdentityEvidence:
    """Non-PII explanation of one identity match."""

    kind: str
    source: str
    reference: str | None = None


@dataclass(frozen=True)
class IdentityMatch:
    """Resolved contributor identity and the confidence of the merge."""

    canonical_contributor_id: str
    confidence: float
    evidence: tuple[IdentityEvidence, ...] = ()
    review_required: bool = False
    affiliation: str | None = None
    is_bot: bool = False
    mapping_version: str = IDENTITY_MAPPING_VERSION

    @property
    def id(self) -> str:
        """Compatibility alias for callers using the SortingHat ``mk`` term."""
        return self.canonical_contributor_id


@dataclass(frozen=True)
class _Candidate:
    contributor_id: str
    email: str | None = None
    login: str | None = None
    name: str | None = None
    aliases: tuple[str, ...] = ()
    affiliation: str | None = None
    is_bot: bool = False
    source: str = "collectoss"


def _collectoss_source() -> Path:
    source = workspace_root() / "vendor" / "collectoss"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    return source


def _sortinghat_source() -> Path:
    source = workspace_root() / "vendor" / "chaoss" / "sortinghat"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    return source


def copied_identity_models_available() -> tuple[str, ...]:
    """Probe the copied model/recommendation modules without importing eagerly."""
    available: list[str] = []
    try:
        _collectoss_source()
        importlib.import_module("collectoss.application.db.models.data")
        available.append("collectoss.models")
    except (ImportError, OSError):
        pass
    try:
        _sortinghat_source()
        importlib.import_module("sortinghat.core.models")
        importlib.import_module("sortinghat.core.recommendations.engine")
        available.append("sortinghat.models")
    except (ImportError, OSError):
        pass
    return tuple(available)


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _email(value: object) -> str | None:
    normalized = canonicalize_author_email(str(value)) if value else None
    return normalized or None


def _hash_identity(value: str) -> str:
    return f"unresolved:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _source_value(row: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _candidate(row: Mapping[str, Any], *, source: str = "collectoss") -> _Candidate | None:
    contributor_id = _source_value(row, "canonical_contributor_id", "cntrb_id", "individual_id", "mk", "uuid", "id")
    if contributor_id in (None, ""):
        email = _email(_source_value(row, "email", "cntrb_email", "canonical_email"))
        login = _norm(_source_value(row, "login", "cntrb_login", "username", "gh_login")) or None
        contributor_id = email or login
    if contributor_id in (None, ""):
        return None
    alias_values = row.get("aliases") or row.get("alias_emails") or ()
    if isinstance(alias_values, str):
        alias_values = (alias_values,)
    aliases = tuple(sorted({_norm(_email(item) or item) for item in alias_values if item}))
    email = _email(_source_value(row, "email", "cntrb_email", "canonical_email"))
    login = _norm(_source_value(row, "login", "cntrb_login", "username", "gh_login")) or None
    name = _norm(_source_value(row, "name", "full_name", "cntrb_full_name")) or None
    affiliation = _source_value(row, "affiliation", "organization", "company", "ca_affiliation")
    kind = _norm(_source_value(row, "type", "cntrb_type"))
    return _Candidate(
        contributor_id=str(contributor_id),
        email=email,
        login=login,
        name=name,
        aliases=aliases,
        affiliation=str(affiliation) if affiliation else None,
        is_bot=bool(row.get("is_bot")) or kind in {"bot", "robot"} or bool(login and login.endswith("[bot]")),
        source=source,
    )


def _rows(context: AnalyzerContext, key: str) -> Iterable[Mapping[str, Any]]:
    values = context.inventory.get(key)
    if isinstance(values, Mapping):
        values = values.values()
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        return ()
    return (value for value in values if isinstance(value, Mapping))


def _config(context: AnalyzerContext) -> dict[str, Any]:
    supplied = context.inventory.get("identity_config")
    if isinstance(supplied, Mapping):
        return dict(supplied)
    path = workspace_root() / "config" / "identity.yaml"
    try:
        import yaml

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        return dict(loaded) if isinstance(loaded, Mapping) else {}
    except (ImportError, OSError, ValueError):
        return {}


def _as_float(value: object, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


class IdentityResolver:
    """Resolve aliases using copied CollectOSS/SortingHat-shaped rows.

    No source row is modified.  The resolver builds a deterministic lookup
    index once and returns a derived mapping view for the current run.
    """

    def __init__(self, context: AnalyzerContext) -> None:
        self.context = context
        config = _config(context)
        self.mapping_version = str(config.get("mapping_version") or IDENTITY_MAPPING_VERSION)
        self.min_merge_confidence = _as_float(config.get("min_merge_confidence"), 0.8)
        self.review_below = _as_float(config.get("review_below"), self.min_merge_confidence)
        self.manual_overrides = {
            _norm(key): str(value.get("canonical_contributor_id") or value.get("id") or value)
            if isinstance(value, Mapping)
            else str(value)
            for key, value in (config.get("manual_overrides") or {}).items()
        }
        self.candidates = self._build_candidates()
        self._by_email: dict[str, list[_Candidate]] = {}
        self._by_login: dict[str, list[_Candidate]] = {}
        self._by_name: dict[str, list[_Candidate]] = {}
        self._by_alias: dict[str, list[_Candidate]] = {}
        for candidate in self.candidates:
            if candidate.email:
                self._by_email.setdefault(candidate.email, []).append(candidate)
            if candidate.login:
                self._by_login.setdefault(candidate.login, []).append(candidate)
            if candidate.name:
                self._by_name.setdefault(candidate.name, []).append(candidate)
            for alias in candidate.aliases:
                self._by_alias.setdefault(alias, []).append(candidate)
        log.debug(
            "index_built repo_id=%s candidate_count=%d copied_models=%s",
            context.repo_id,
            len(self.candidates),
            copied_identity_models_available(),
        )

    def _build_candidates(self) -> tuple[_Candidate, ...]:
        rows: list[_Candidate] = []
        for key in ("contributors", "collectoss_contributors", "sortinghat_identities"):
            source = "sortinghat" if "sortinghat" in key else "collectoss"
            for row in _rows(self.context, key):
                candidate = _candidate(row, source=source)
                if candidate:
                    rows.append(candidate)
        for row in _rows(self.context, "contributor_aliases"):
            alias = _norm(_email(_source_value(row, "alias_email", "email")) or _source_value(row, "alias_email", "email"))
            target = _source_value(row, "canonical_contributor_id", "cntrb_id", "canonical_email")
            if not alias or target in (None, ""):
                continue
            rows.append(_Candidate(str(target), aliases=(alias,), source="collectoss.alias"))
        unique: dict[tuple[str, str | None, str | None], _Candidate] = {}
        for row in rows:
            key = (row.contributor_id, row.email, row.login)
            previous = unique.get(key)
            if previous is None:
                unique[key] = row
            else:
                unique[key] = _Candidate(
                    contributor_id=row.contributor_id,
                    email=row.email or previous.email,
                    login=row.login or previous.login,
                    name=row.name or previous.name,
                    aliases=tuple(sorted(set(previous.aliases) | set(row.aliases))),
                    affiliation=row.affiliation or previous.affiliation,
                    is_bot=row.is_bot or previous.is_bot,
                    source=previous.source,
                )
        return tuple(sorted(unique.values(), key=lambda item: (item.contributor_id, item.email or "", item.login or "")))

    def _manual(self, raw: Mapping[str, Any]) -> str | None:
        for key in (
            _norm(_source_value(raw, "canonical_contributor_id", "id", "uuid")),
            _norm(_source_value(raw, "email", "author_email", "cntrb_email")),
            _norm(_source_value(raw, "login", "username", "author_login")),
            _norm(_source_value(raw, "name", "author_name")),
        ):
            if key and key in self.manual_overrides:
                return self.manual_overrides[key]
        return None

    @staticmethod
    def _author(raw_author: Mapping[str, Any] | str) -> dict[str, Any]:
        if isinstance(raw_author, str):
            return {"name": raw_author}
        return dict(raw_author)

    def resolve(self, raw_author: Mapping[str, Any] | str) -> IdentityMatch:
        raw = self._author(raw_author)
        email = _email(_source_value(raw, "email", "author_email", "cntrb_email"))
        login = _norm(_source_value(raw, "login", "username", "author_login", "cntrb_login")) or None
        name = _norm(_source_value(raw, "name", "author_name", "full_name", "cntrb_full_name")) or None
        raw_id = _norm(_source_value(raw, "id", "uuid", "cntrb_id", "canonical_contributor_id")) or None
        override = self._manual(raw)
        if override:
            evidence = (IdentityEvidence("manual_override", "config/identity.yaml", "manual_overrides"),)
            log.info("manual_override_applied repo_id=%s key_type=%s", self.context.repo_id, "configured")
            return IdentityMatch(override, 1.0, evidence, False, _source_value(raw, "affiliation", "company"), bool(raw.get("is_bot")), self.mapping_version)

        candidates: list[tuple[_Candidate, float, str]] = []
        for candidate in self._by_email.get(email or "", ()):
            candidates.append((candidate, 1.0, "email"))
        for candidate in self._by_login.get(login or "", ()):
            candidates.append((candidate, 1.0, "login"))
        for candidate in self._by_alias.get(email or "", ()):
            candidates.append((candidate, 0.95, "alias"))
        if name:
            for candidate in self._by_name.get(name, ()):
                candidates.append((candidate, 0.65, "name"))
        if raw_id:
            candidates.extend((candidate, 1.0, "source_id") for candidate in self.candidates if candidate.contributor_id.casefold() == raw_id)

        best_by_id: dict[str, tuple[_Candidate, float, str]] = {}
        for candidate, confidence, kind in candidates:
            previous = best_by_id.get(candidate.contributor_id)
            if previous is None or confidence > previous[1]:
                best_by_id[candidate.contributor_id] = (candidate, confidence, kind)
        ranked = sorted(best_by_id.values(), key=lambda item: (-item[1], item[0].contributor_id))
        ambiguous = len(ranked) > 1 and ranked[0][1] == ranked[1][1]
        if ambiguous:
            key = author_identity_key(name, email) or name or login or "unknown"
            identity = _hash_identity(key)
            log.warning("ambiguous_alias repo_id=%s key_type=%s candidate_count=%d", self.context.repo_id, "identity", len(ranked))
            return IdentityMatch(
                identity,
                0.25,
                (IdentityEvidence("ambiguous", "sortinghat.recommendations", f"candidates:{len(ranked)}"),),
                True,
                None,
                bool(raw.get("is_bot")),
                self.mapping_version,
            )
        if ranked:
            candidate, confidence, kind = ranked[0]
            review = confidence < self.review_below
            if review:
                log.warning("low_confidence_alias repo_id=%s key_type=%s confidence=%.2f", self.context.repo_id, kind, confidence)
            return IdentityMatch(
                candidate.contributor_id,
                confidence,
                (IdentityEvidence(kind, candidate.source),),
                review,
                candidate.affiliation,
                candidate.is_bot or bool(raw.get("is_bot")),
                self.mapping_version,
            )

        key = author_identity_key(name, email) or name or login or raw_id or "unknown"
        log.warning("identity_unresolved repo_id=%s key_type=%s", self.context.repo_id, "anonymous" if key == "unknown" else "raw")
        return IdentityMatch(
            _hash_identity(key),
            0.4,
            (IdentityEvidence("unresolved", "identity.resolver"),),
            True,
            None,
            bool(raw.get("is_bot")),
            self.mapping_version,
        )

    def resolve_many(self, authors: Iterable[Mapping[str, Any] | str]) -> tuple[IdentityMatch, ...]:
        return tuple(self.resolve(author) for author in authors)


def _fact_author(fact: RawFact) -> Mapping[str, Any] | None:
    payload = fact.payload
    for key in ("author", "user", "actor", "reviewer", "contributor"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            return {"name": value}
    if any(payload.get(key) for key in ("author_email", "email", "author_name", "name", "login")):
        return {
            "email": payload.get("author_email") or payload.get("email"),
            "name": payload.get("author_name") or payload.get("name"),
            "login": payload.get("author_login") or payload.get("login"),
            "id": payload.get("author_id") or payload.get("user_id"),
            "is_bot": payload.get("is_bot"),
        }
    return None


def _evidence(context: AnalyzerContext, fact: RawFact, *, confidence: float = 1.0) -> EvidenceRef:
    return EvidenceRef(
        source=fact.source,
        source_commit=fact.source_version,
        json_pointer=f"/events/{fact.event_type}/{fact.stable_event_id}",
        collected_at=fact.updated_at or context.as_of_ts,
        confidence=confidence,
        redaction="partial",
    )


class IdentityAdapter:
    """Map immutable raw events to contributor and bus-factor facts."""

    definition = IDENTITY_DEFINITION

    def result(self, context: AnalyzerContext) -> AnalyzerResult:
        resolver = IdentityResolver(context)
        from .temporal_adapter import raw_facts_from_context

        facts = raw_facts_from_context(context)
        matches: list[tuple[RawFact, IdentityMatch]] = []
        for fact in facts:
            author = _fact_author(fact)
            if author is not None:
                matches.append((fact, resolver.resolve(author)))
        counts = Counter(match.canonical_contributor_id for _, match in matches if not match.is_bot)
        config = _config(context)
        bus_cfg = config.get("bus_factor") if isinstance(config.get("bus_factor"), Mapping) else {}
        share_threshold = _as_float((bus_cfg or {}).get("share_threshold"), 0.8)
        population_scope = str((bus_cfg or {}).get("population_scope") or "non_bot_events")
        total = sum(counts.values())
        running = 0
        bus_factor = 0
        for _, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            running += count
            bus_factor += 1
            if total and running / total >= share_threshold:
                break
        unique_matches = {match.canonical_contributor_id: match for _, match in matches}
        review_matches = [match for match in unique_matches.values() if match.review_required]
        evidence = tuple(_evidence(context, fact, confidence=match.confidence) for fact, match in matches)
        metrics = (
            MetricValue(name="contributors:unique", dimension="community", value=len(unique_matches), unit="contributors", denominator=len(matches), evidence_refs=evidence[:1]),
            MetricValue(name="contributors:resolved", dimension="community", value=sum(not match.review_required for match in unique_matches.values()), unit="contributors", denominator=len(unique_matches), evidence_refs=evidence[:1]),
            MetricValue(name="contributors:bus_factor", dimension="community", value=bus_factor if total else None, unit="contributors", denominator=total, evidence_refs=evidence[:1]),
            MetricValue(name="contributors:events", dimension="community", value=len(matches), unit="events", denominator=len(facts), evidence_refs=evidence[:1]),
        )
        findings: list[Finding] = []
        for index, match in enumerate(sorted(review_matches, key=lambda item: item.canonical_contributor_id)):
            findings.append(
                Finding(
                    id=f"{IDENTITY_ANALYZER_ID}:review:{index}",
                    analyzer_id=IDENTITY_ANALYZER_ID,
                    subject=match.canonical_contributor_id,
                    dimension="community",
                    severity="medium" if match.confidence >= 0.4 else "high",
                    confidence=match.confidence,
                    reason="Contributor alias is unresolved or below the configured merge confidence; it remains a separate identity.",
                    evidence_refs=tuple(ref for ref in evidence if ref.confidence == match.confidence)[:1],
                    remediation="Review the alias in config/identity.yaml manual_overrides.",
                )
            )
        if any(match.is_bot for match in unique_matches.values()):
            findings.append(
                Finding(
                    id=f"{IDENTITY_ANALYZER_ID}:bots",
                    analyzer_id=IDENTITY_ANALYZER_ID,
                    subject="contributors",
                    dimension="community",
                    severity="info",
                    confidence=1.0,
                    reason="Bot or agent identities are kept separate from the human bus-factor population.",
                )
            )
        status = AnalyzerStatus.WARN if findings else AnalyzerStatus.PASS if matches else AnalyzerStatus.INCONCLUSIVE
        limitation = () if matches else (Limitation(reason="No contributor-bearing raw events were supplied", kind="insufficient_denominator"),)
        log.info(
            "resolved repo_id=%s mapping_version=%s raw_events=%d resolved=%d review=%d",
            context.repo_id,
            resolver.mapping_version,
            len(facts),
            len(unique_matches) - len(review_matches),
            len(review_matches),
        )
        return AnalyzerResult(
            analyzer_id=IDENTITY_ANALYZER_ID,
            analyzer_version=resolver.mapping_version,
            status=status,
            metrics=metrics if matches else (),
            findings=tuple(findings),
            evidence=evidence,
            limitations=limitation,
            source_versions={"collectoss": COLLECTOSS_COMMIT, "sortinghat": SORTINGHAT_COMMIT},
            available_weight=float(len(metrics) if matches else 0),
            total_weight=float(len(metrics)),
            diagnostics={
                "mapping_version": resolver.mapping_version,
                "raw_fact_count": len(facts),
                "identity_count": len(unique_matches),
                "review_count": len(review_matches),
                "bus_factor": bus_factor if total else None,
                "bus_factor_share_threshold": share_threshold,
                "bus_factor_population_scope": population_scope,
                "immutable_raw": True,
                "source_event_ids": [fact.stable_event_id for fact, _ in matches],
            },
        )


def identity_adapter(context: AnalyzerContext) -> AnalyzerResult:
    return IdentityAdapter().result(context)


def enrich_git_meta_map(context: AnalyzerContext, git_meta_map: Mapping[str, Any]) -> dict[str, Any]:
    """Attach canonical ownership to the existing GitIndexer input shape.

    ``HealthAnalyzer`` continues to receive its normal ``git_meta_map``.  The
    enrichment only adds fields to copied metadata rows, so the existing
    ownership/hotspot/prior-defect algorithms remain the execution boundary.
    """
    resolver = IdentityResolver(context)
    from .temporal_adapter import EventNormalizer, build_temporal_window, raw_facts_from_context

    raw_facts = raw_facts_from_context(context)
    normalized = tuple(EventNormalizer(context).normalize(fact) for fact in raw_facts)
    temporal_config = context.inventory.get("temporal_config") if isinstance(context.inventory.get("temporal_config"), Mapping) else {}
    temporal_window = build_temporal_window(
        normalized,
        as_of_ts=context.as_of_ts,
        window_days=int(temporal_config.get("window_days", 90)),
        half_life_days=float(temporal_config.get("half_life_days", 30.0)),
        mass_edit_threshold=int(temporal_config.get("mass_edit_threshold", 1000)),
    )
    enriched: dict[str, Any] = {}
    for path, original in git_meta_map.items():
        if not isinstance(original, Mapping):
            enriched[path] = original
            continue
        row = dict(original)
        raw_top = row.get("top_authors_json")
        try:
            authors = json.loads(raw_top) if isinstance(raw_top, str) else raw_top
        except (TypeError, ValueError):
            authors = []
        canonical_authors: list[dict[str, Any]] = []
        if isinstance(authors, list):
            for author in authors:
                if not isinstance(author, Mapping):
                    continue
                match = resolver.resolve({"name": author.get("name"), "email": author.get("email")})
                canonical = dict(author)
                canonical["canonical_contributor_id"] = match.canonical_contributor_id
                canonical["identity_confidence"] = match.confidence
                canonical["identity_review_required"] = match.review_required
                canonical_authors.append(canonical)
        row["canonical_top_authors_json"] = json.dumps(canonical_authors, sort_keys=True)
        if canonical_authors:
            primary = canonical_authors[0]
            row["primary_owner_canonical_id"] = primary["canonical_contributor_id"]
            row["primary_owner_identity_confidence"] = primary["identity_confidence"]
        row["identity_mapping_version"] = str(_config(context).get("mapping_version") or IDENTITY_MAPPING_VERSION)
        row["temporal_window_start"] = temporal_window.start_ts.isoformat()
        row["temporal_window_end"] = temporal_window.end_ts.isoformat()
        row["temporal_normalization_policy"] = temporal_window.policy_version
        enriched[path] = row
    log.debug("git_meta_enriched repo_id=%s files=%d", context.repo_id, len(enriched))
    return enriched


def register_identity_adapters(registry: Any) -> None:
    if IDENTITY_ANALYZER_ID not in registry.ids():
        registry.register(IDENTITY_DEFINITION, identity_adapter)


__all__ = [
    "IDENTITY_ANALYZER_ID",
    "IDENTITY_DEFINITION",
    "IDENTITY_MAPPING_VERSION",
    "IdentityAdapter",
    "IdentityEvidence",
    "IdentityMatch",
    "IdentityResolver",
    "copied_identity_models_available",
    "enrich_git_meta_map",
    "identity_adapter",
    "register_identity_adapters",
]
