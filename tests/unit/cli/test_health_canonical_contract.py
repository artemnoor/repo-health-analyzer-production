"""CLI presentation contract for persisted repository health projections."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

from click.testing import CliRunner
from rich.console import Console

from repowise.cli.commands.health_cmd.command import health_command
from repowise.cli.commands.health_cmd.summary import (
    _render_canonical_score,
    canonical_score_label,
    canonical_score_markdown,
)


def canonical_report(score: float | None, *, include_projection: bool = True) -> dict:
    report = {
        "snapshot": {"status": "warn", "score": 9.1},
        "coverage": 0.75,
        "limitations": [],
    }
    if include_projection:
        report["score_projection"] = {
            "overall_score": score,
            "status": "warn",
            "coverage": 0.75,
        }
    return report


def render_canonical(report: dict | None) -> str:
    stream = io.StringIO()
    console = Console(file=stream, width=120, force_terminal=False)
    with patch("repowise.cli.commands.health_cmd.summary.console", console):
        _render_canonical_score(report)
    return stream.getvalue()


def test_table_renderer_labels_repository_score_as_100_and_keeps_legacy_snapshot_separate() -> None:
    output = render_canonical(canonical_report(82.5))

    assert "Canonical repository health:" in output
    assert "82.5/100" in output
    assert "status=warn" in output
    assert "9.1/10" not in output


def test_zero_is_measured_and_null_or_missing_projection_is_unavailable() -> None:
    assert canonical_score_label(canonical_report(0)) == "0.0/100"
    assert canonical_score_label(canonical_report(None)) == "unavailable"
    assert canonical_score_label(canonical_report(9.1, include_projection=False)) == "unavailable"
    assert "0.0/100" in render_canonical(canonical_report(0))
    assert "unavailable" in render_canonical(canonical_report(None))
    assert "no persisted 0–100 projection" in render_canonical(
        canonical_report(9.1, include_projection=False)
    )


def test_markdown_and_json_contracts_keep_canonical_projection_additive() -> None:
    report = canonical_report(82.5)

    assert canonical_score_markdown(report) == "- **canonical_repository_health**: 82.5/100"
    payload = {
        "kpis": {"average_health": 9.1},
        "canonical": report,
        "explain": {
            "canonical_repository_health": canonical_score_label(report),
            "canonical_score_scale": 100,
        },
    }
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert decoded["kpis"]["average_health"] == 9.1
    assert decoded["canonical"]["score_projection"]["overall_score"] == 82.5
    assert decoded["explain"]["canonical_score_scale"] == 100


def test_explain_help_names_both_score_scales() -> None:
    result = CliRunner().invoke(health_command, ["--help"])

    assert result.exit_code == 0
    assert "repository score" in result.output
    assert "file KPIs remain" in result.output
