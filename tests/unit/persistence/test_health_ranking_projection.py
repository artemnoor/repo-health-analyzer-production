from datetime import UTC, datetime

from repowise.core.analysis.health.ranking_projection import (
    RankingCandidate,
    normalize_filter,
    rank_candidates,
)


def _row(repository_id: str, *, score: float, language: str, **overrides) -> RankingCandidate:
    values = dict(
        repository_id=repository_id,
        name=repository_id,
        url="",
        visibility="public",
        snapshot_id="s-" + repository_id,
        score_config_digest="cfg",
        overall_score=score,
        status="pass",
        dimensions={"security": score},
        languages=(language,),
        confidence=0.9,
        coverage=0.9,
        evidence_coverage=0.9,
        analyzed_at=datetime(2026, 9, 10, tzinfo=UTC),
        mode="full",
        eligible=True,
    )
    values.update(overrides)
    return RankingCandidate(**values)


def test_filters_are_composable_without_changing_rank_order() -> None:
    rows = [
        _row("python-high", score=92, language="python"),
        _row("rust-mid", score=82, language="rust"),
        _row("python-low", score=61, language="python"),
    ]
    page, total = rank_candidates(
        rows,
        ranking_filter=normalize_filter(language="python", dimension="security"),
        page=1,
        limit=2,
    )

    assert total == 2
    assert [row.repository_id for row in page] == ["python-high", "python-low"]


def test_unknown_dimension_filter_returns_no_rows() -> None:
    rows, total = rank_candidates(
        [_row("repo", score=88, language="python")],
        ranking_filter=normalize_filter(dimension="tests"),
    )
    assert rows == []
    assert total == 0
