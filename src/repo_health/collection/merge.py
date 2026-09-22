"""Deterministic, lossless merging of normalized repository facts."""

from __future__ import annotations

from collections.abc import Iterable

from ..contracts.results import FactGroup, Limitation, RepositoryFacts

_GROUP_NAMES = ("git", "documentation", "issues", "cicd", "security", "code_health")


def _unique_limitations(items: Iterable[Limitation]) -> tuple[Limitation, ...]:
    unique = {(item.code, item.reason, item.affected_scope): item for item in items}
    return tuple(unique[key] for key in sorted(unique))


def merge_fact_group(left: FactGroup, right: FactGroup) -> FactGroup:
    """Union observations and limitations; right-side values own duplicate keys."""

    if type(left) is not type(right):
        raise TypeError(f"cannot merge different fact groups: {type(left).__name__}, {type(right).__name__}")
    observations = {item.key: item for item in left.observations}
    observations.update({item.key: item for item in right.observations})
    values: dict[str, object] = {
        "available": left.available or right.available,
        "observations": tuple(observations[key] for key in sorted(observations)),
        "limitations": _unique_limitations((*left.limitations, *right.limitations)),
    }
    # SecurityFacts carries lifecycle state in addition to the common fact
    # group fields.  Preserve it across the generic merge boundary so a
    # finished/no-scan/failed AppSec result cannot silently become ambiguous.
    if hasattr(left, "scan_state"):
        values["scan_state"] = right.scan_state or left.scan_state
    return type(left)(
        **values,
    )


def merge_repository_facts(left: RepositoryFacts, right: RepositoryFacts) -> RepositoryFacts:
    """Merge one collector result without dropping independent source evidence."""

    statuses = {item.source_id: item for item in left.source_statuses}
    statuses.update({item.source_id: item for item in right.source_statuses})
    capabilities = {item.capability_id: item for item in left.capability_states}
    capabilities.update({item.capability_id: item for item in right.capability_states})
    updates: dict[str, object] = {
        "repository": right.repository or left.repository,
        "assessment_profile": (
            right.assessment_profile
            if left.assessment_profile.value == "public" and right.assessment_profile.value == "owner_extended"
            else left.assessment_profile
        ),
        "source_snapshot_digest": right.source_snapshot_digest or left.source_snapshot_digest,
        "collected_at": right.collected_at or left.collected_at,
        "source_versions": {**left.source_versions, **right.source_versions},
        "source_statuses": tuple(statuses[key] for key in sorted(statuses)),
        "capabilities": tuple(sorted(set(left.capabilities) | set(right.capabilities))),
        "used_sources": tuple(sorted(set(left.used_sources) | set(right.used_sources) | set(statuses))),
        "capability_states": tuple(capabilities[key] for key in sorted(capabilities)),
        "limitations": _unique_limitations((*left.limitations, *right.limitations)),
    }
    for group_name in _GROUP_NAMES:
        updates[group_name] = merge_fact_group(getattr(left, group_name), getattr(right, group_name))
    return left.model_copy(update=updates)


__all__ = ["merge_fact_group", "merge_repository_facts"]
