"""Lossless normalized fact aggregation tests."""

from __future__ import annotations

from repo_health.collection.merge import merge_fact_group, merge_repository_facts
from repo_health.contracts.results import CodeHealthFacts, Limitation, RepositoryFacts


def test_fact_group_merge_unions_observations_and_right_side_owns_duplicate() -> None:
    left = CodeHealthFacts(available=True, observations=({"key": "ncloc", "value": 10},))
    right = CodeHealthFacts(
        available=False,
        observations=({"key": "ncloc", "value": 20}, {"key": "todo_count", "value": 3}),
        limitations=(Limitation(code="sonar.unavailable", reason="SonarQube is unavailable"),),
    )

    merged = merge_fact_group(left, right)

    assert merged.available is True
    assert {item.key: item.value for item in merged.observations} == {"ncloc": 20, "todo_count": 3}
    assert merged.limitations[0].code == "sonar.unavailable"


def test_repository_fact_merge_is_deterministic_and_preserves_source_statuses() -> None:
    left = RepositoryFacts(code_health=CodeHealthFacts(observations=({"key": "ncloc", "value": 10},)))
    right = RepositoryFacts(code_health=CodeHealthFacts(observations=({"key": "max_blob_size", "value": 3},)))

    first = merge_repository_facts(left, right)
    second = merge_repository_facts(RepositoryFacts(code_health=right.code_health), left)

    assert {item.key for item in first.code_health.observations} == {"ncloc", "max_blob_size"}
    assert first.code_health.digest() == first.code_health.model_copy().digest()
    assert first.digest() == merge_repository_facts(left, right).digest()
    assert first.digest() == second.digest()
