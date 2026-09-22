from __future__ import annotations

from datetime import UTC, datetime

from repo_health.analyzers.activity import ActivityAnalyzer
from repo_health.collection.git.pydriller import _identity_limitations, _identity_observations
from repo_health.contracts.requests import RepositoryRef
from repo_health.contracts.results import AnalyzerInput, GitFacts, RepositoryFacts

REPOSITORY = RepositoryRef(
    repository_id="acme/example",
    canonical_uri="https://github.com/acme/example",
    provider="github",
    ref="main",
    head_sha="a" * 40,
)
AS_OF = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _input(*, collected_at: datetime, as_of: datetime = AS_OF) -> AnalyzerInput:
    facts = RepositoryFacts(
        repository=REPOSITORY,
        collected_at=collected_at,
        git=GitFacts(
            available=True,
            observations=(
                {"key": "unique_commits", "value": 12},
                {"key": "commits_90d", "value": 5},
                {"key": "authors_90d", "value": 2},
                {"key": "empty_commits", "value": 0},
                {"key": "meaningful_ratio", "value": 1.0},
                {"key": "latest_activity_at", "value": "2026-09-18T12:00:00Z"},
            ),
        ),
    )
    return AnalyzerInput(
        analysis_id="activity-determinism",
        as_of=as_of,
        repository=REPOSITORY,
        analyzer_id=ActivityAnalyzer.id,
        analyzer_version=ActivityAnalyzer.version,
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
    )


def _scoring_projection(result: object) -> dict[str, object]:
    payload = result.model_dump(mode="json")  # type: ignore[union-attr]
    payload["evidence"] = [
        {
            "evidence_id": item["evidence_id"],
            "source": item["source"],
            "source_version": item["source_version"],
            "confidence": item["confidence"],
        }
        for item in payload["evidence"]
    ]
    return payload


def test_activity_result_is_independent_of_collection_wall_clock() -> None:
    analyzer = ActivityAnalyzer()
    first = analyzer.analyze(_input(collected_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC)))
    second = analyzer.analyze(_input(collected_at=datetime(2030, 1, 1, 12, 0, tzinfo=UTC)))

    assert _scoring_projection(first) == _scoring_projection(second)
    assert first.score == second.score


def test_activity_changes_only_when_explicit_as_of_changes() -> None:
    analyzer = ActivityAnalyzer()
    current = analyzer.analyze(_input(collected_at=datetime(2026, 9, 21, tzinfo=UTC)))
    older_reference = analyzer.analyze(
        _input(
            collected_at=datetime(2026, 9, 21, tzinfo=UTC),
            as_of=datetime(2027, 9, 21, 12, 0, tzinfo=UTC),
        )
    )

    assert current.score != older_reference.score


def test_contributor_identity_does_not_merge_ambiguous_variants() -> None:
    observations = _identity_observations(
        author_emails={"alice": {"alice@one.invalid", "alice@two.invalid"}},
        email_names={"alice@one.invalid": {"alice"}, "alice@two.invalid": {"alice"}},
        missing_email_count=0,
        author_count=1,
    )

    assert observations["contributor_identity_policy"] == "git_name_count_no_merge"
    assert observations["contributor_identity_ambiguous"] is True
    assert observations["contributor_identity_variant_count"] == 1
    assert observations["contributor_identity_confidence"] == 0.75
    assert {item.code for item in _identity_limitations(observations)} == {"git.contributor_identity_ambiguous"}


def test_contributor_identity_missing_email_is_explicit_limitation() -> None:
    observations = _identity_observations(
        author_emails={},
        email_names={},
        missing_email_count=2,
        author_count=1,
    )

    assert observations["contributor_identity_ambiguous"] is False
    assert observations["contributor_identity_confidence"] == 0.5
    assert {item.code for item in _identity_limitations(observations)} == {"git.contributor_identity_missing_email"}
