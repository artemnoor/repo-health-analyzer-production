"""Replay, cache, and public-boundary checks for Vale results."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repowise.core.analysis.analyzer_integration.cache import FileAnalyzerCache, cache_key
from repowise.core.analysis.analyzer_integration.contracts import (
    AnalyzerContext,
    AnalyzerResult,
    AnalyzerStatus,
    EvidenceRef,
)
from repowise.core.analysis.analyzer_integration.process import ProcessOutput

ROOT = Path(__file__).resolve().parents[2]

from repowise.core.analysis.health.integrations.contracts import (  # noqa: E402
    EvidenceRef as HealthEvidenceRef,
)
from repowise.core.analysis.health.integrations.vale_adapter import (  # noqa: E402
    VALE_ANALYZER_ID,
    VALE_DEFINITION,
    ValeAdapter,
)


class FakeProcess:
    def __init__(self, *outputs: ProcessOutput) -> None:
        self.outputs = list(outputs)

    def run(self, _request: Any) -> ProcessOutput:
        return self.outputs.pop(0)


def _output(stdout: str) -> ProcessOutput:
    return ProcessOutput(
        tool_id=VALE_ANALYZER_ID,
        exit_code=0,
        stdout=stdout,
        stderr="",
        duration_ms=1,
    )


def _context(repo: Path) -> AnalyzerContext:
    return AnalyzerContext(
        repo_path=repo,
        repo_id="vale-replay",
        head_sha="replay-head",
        as_of_ts=datetime(2026, 9, 18, tzinfo=UTC),
        capabilities=("local_scan",),
        tool_paths={"vale": sys.executable},
        cache_dir=repo / ".cache",
    )


def _result(tmp_path: Path) -> tuple[AnalyzerContext, AnalyzerResult]:
    (tmp_path / "README.md").write_text("AWS-shaped wording.", encoding="utf-8")
    diagnostics = {
        "README.md": [
            {
                "Check": "RepoHealth.Clarity",
                "Severity": "warning",
                "Message": "Use precise wording.",
                "Line": 1,
                "Match": "AWS-shaped",
            }
        ]
    }
    context = _context(tmp_path)
    result = ValeAdapter(
        process=FakeProcess(_output(json.dumps(diagnostics)), _output(json.dumps({"words": 30}))),
        project_root=ROOT,
    ).run(context)
    return context, result


def test_vale_result_persists_and_replays_without_raw_payload_or_tool_path(tmp_path: Path) -> None:
    context, result = _result(tmp_path)
    cache = FileAnalyzerCache(tmp_path / "cache")
    key = cache_key(VALE_DEFINITION, context)
    cache.put(key, result, analyzer_id=VALE_ANALYZER_ID)
    replayed = cache.get(
        key,
        analyzer_id=VALE_ANALYZER_ID,
        analyzer_version=VALE_DEFINITION.version,
    )

    assert replayed is not None
    assert replayed.cache_hit is True
    assert replayed.model_copy(update={"cache_hit": False}) == result
    public_json = replayed.model_dump_json()
    assert "AWS-shaped" not in public_json
    assert sys.executable not in public_json
    assert replayed.raw_payload_ref and replayed.raw_payload_ref.startswith("vale://")
    assert replayed.evidence[0].snippet_hash
    assert replayed.evidence[0].redaction == "partial"


def test_policy_version_change_invalidates_cache_key_and_old_snapshot_stays_valid(
    tmp_path: Path,
) -> None:
    context, result = _result(tmp_path)
    changed_definition = VALE_DEFINITION.model_copy(
        update={"version": f"{VALE_DEFINITION.version}-policy-change"}
    )
    assert cache_key(VALE_DEFINITION, context) != cache_key(changed_definition, context)

    evidence = EvidenceRef(source="repohealth.baseline", collected_at=context.as_of_ts)
    old_snapshot = AnalyzerResult(
        analyzer_id="repohealth.baseline",
        analyzer_version="baseline",
        status=AnalyzerStatus.PASS,
        score=75,
        score_dimension="docs",
        evidence=(evidence,),
        available_weight=1,
        total_weight=1,
    )
    restored = AnalyzerResult.model_validate_json(old_snapshot.model_dump_json())
    assert restored == old_snapshot
    assert result.source_versions["vale_policy"] == "vale-3.22.0-policy-v2"


def test_rescore_of_same_replayed_result_is_deterministic(tmp_path: Path) -> None:
    context, result = _result(tmp_path)
    baseline = AnalyzerResult(
        analyzer_id="repohealth.baseline",
        analyzer_version="baseline",
        status=AnalyzerStatus.PASS,
        score=75,
        score_dimension="docs",
        evidence=(HealthEvidenceRef(source="repohealth.baseline", collected_at=context.as_of_ts),),
        available_weight=1,
        total_weight=1,
    )
    from repowise.core.analysis.health.composite import compose_health_score

    first = compose_health_score((baseline, result), repository_id=context.repo_id)
    second = compose_health_score((baseline, result), repository_id=context.repo_id)
    assert first == second
