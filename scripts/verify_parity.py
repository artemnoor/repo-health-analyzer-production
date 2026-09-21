"""Run deterministic parity gates for the standalone backend boundary.

The script intentionally uses only target-package contracts and fixtures.  It
is suitable for migration checkpoints before the historical monorepo paths are
removed.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from repo_health.analyzers import CANONICAL_ANALYZER_IDS, canonical_registry, register_default_factories
from repo_health.contracts.execution import AnalyzerTask
from repo_health.contracts.requests import AnalysisRequest, RepositoryRef
from repo_health.contracts.results import (
    AnalyzerInput,
    CategoryResult,
    CategoryStatus,
    Confidence,
    Coverage,
    HealthCategory,
    RepositoryFacts,
    ScoreInput,
)
from repo_health.execution.local import LocalExecutor
from repo_health.execution.worker import WorkerExecutor
from repo_health.persistence import SQLitePersistence, replay_legacy_score
from repo_health.scoring.v1 import ScoreEngineV1


def _repository() -> RepositoryRef:
    return RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        head_sha="a" * 40,
    )


def _category(
    analysis_id: str, category: HealthCategory, *, score: float = 80.0, signals: dict[str, int] | None = None
) -> CategoryResult:
    return CategoryResult(
        analysis_id=analysis_id,
        analyzer_id=f"repo-health.{category.value.replace('_', '-')}",
        analyzer_version="parity-fixture-v1",
        category=category,
        status=CategoryStatus.PASS,
        score=score,
        coverage=Coverage(status="complete", covered=1, total=1),
        confidence=Confidence(value=1.0, level="high"),
        score_signals=signals or {},
    )


def score_gate() -> None:
    analysis_id = "parity-score"
    score_input = ScoreInput(
        analysis_id=analysis_id,
        repository=_repository(),
        documentation=_category(analysis_id, HealthCategory.DOCUMENTATION),
        activity=_category(analysis_id, HealthCategory.ACTIVITY),
        issues=_category(analysis_id, HealthCategory.ISSUES),
        cicd=_category(analysis_id, HealthCategory.CICD),
        security=_category(analysis_id, HealthCategory.SECURITY, signals={"high_findings": 1}),
        code_health=_category(analysis_id, HealthCategory.CODE_HEALTH),
        score_engine_version="repo-health-score-v1",
        policy_digest="a" * 64,
    )
    result = ScoreEngineV1().score(score_input)
    if result.score_before_caps != 80.0 or result.overall_score != 60.0 or result.presentation_state != "SCORE":
        raise AssertionError(f"Score v1 parity failed: {result.model_dump(mode='json')}")


def categories_gate() -> None:
    register_default_factories()
    repository = _repository()
    facts = RepositoryFacts(repository=repository)
    for analyzer_id in CANONICAL_ANALYZER_IDS:
        spec, _factory = canonical_registry.get(analyzer_id)  # type: ignore[misc]
        analyzer_input = AnalyzerInput(
            analysis_id="parity-categories",
            repository=repository,
            analyzer_id=analyzer_id,
            analyzer_version=spec.version,
            facts=facts,
            facts_digest=facts.digest(),
            policy_digest="a" * 64,
        )
        result = canonical_registry.run(analyzer_id, analyzer_input)
        if result.analyzer_id != analyzer_id or (not result.evidence and result.status is not CategoryStatus.SKIPPED):
            raise AssertionError(f"category parity failed for {analyzer_id}")


def legacy_gate(*, fail_on_unmapped: bool) -> None:
    names = ("Documentation", "Activity", "Issues", "CI/CD", "Security", "Code Health")
    payload = {
        "score_engine_version": "repo-health-score-v1",
        "overall": 80.0,
        "score_before_cap": 80.0,
        "category_scores": {name: 80.0 for name in names},
        "category_coverage": {name: 100.0 for name in names},
        "category_confidence": {name: 1.0 for name in names},
        "coverage_k": 1.0,
        "confidence": 1.0,
        "evidence_coverage": 0.0,
    }
    result = replay_legacy_score(payload, analysis_id="parity-legacy", repository=_repository())
    if result.overall_score != 80.0 or result.presentation_state != "SCORE":
        raise AssertionError("legacy score replay failed")
    if fail_on_unmapped and any(item.code == "legacy.unmapped_fields" for item in result.limitations):
        raise AssertionError("legacy replay contains unmapped fields")


def _task() -> AnalyzerTask:
    register_default_factories()
    repository = _repository()
    request = AnalysisRequest(
        repository=repository, as_of=datetime(2026, 1, 1, tzinfo=UTC), idempotency_key="parity-worker"
    )
    analyzer_id = "repo-health.issues"
    spec, _factory = canonical_registry.get(analyzer_id)  # type: ignore[misc]
    facts = RepositoryFacts(repository=repository)
    analyzer_input = AnalyzerInput(
        analysis_id=request.analysis_id,
        repository=repository,
        analyzer_id=analyzer_id,
        analyzer_version=spec.version,
        facts=facts,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
    )
    return AnalyzerTask(
        analysis_id=request.analysis_id,
        analyzer_id=analyzer_id,
        analyzer_version=spec.version,
        category=HealthCategory.ISSUES,
        input=analyzer_input,
        facts_digest=facts.digest(),
        policy_digest="a" * 64,
    )


async def execution_gate(modes: list[str]) -> None:
    register_default_factories()
    factories = {analyzer_id: canonical_registry.get(analyzer_id)[1] for analyzer_id in CANONICAL_ANALYZER_IDS}  # type: ignore[index]
    task = _task()
    outcomes = {}
    if "local" in modes:
        outcomes["local"] = await LocalExecutor(factories).execute(task)
    if "worker" in modes:
        persistence = SQLitePersistence()
        persistence.create_analysis(
            AnalysisRequest(
                repository=_repository(),
                analysis_id=task.analysis_id,
                as_of=datetime(2026, 1, 1, tzinfo=UTC),
                idempotency_key="parity-worker",
            )
        )
        worker = WorkerExecutor(persistence=persistence, local=LocalExecutor(factories), worker_id="parity-worker")
        worker.enqueue(task)
        outcomes["worker"] = await worker.run_once()
        persistence.close()
    for mode, outcome in outcomes.items():
        if outcome is None or outcome.result.status is CategoryStatus.ERROR:
            raise AssertionError(f"{mode} execution did not produce a usable result")
    if len(outcomes) == 2 and outcomes["local"].result.to_json() != outcomes["worker"].result.to_json():
        raise AssertionError("local and worker CategoryResult payloads differ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score-only", action="store_true")
    parser.add_argument("--categories", choices=("all",))
    parser.add_argument("--legacy-replay", action="store_true")
    parser.add_argument("--fail-on-unmapped", action="store_true")
    parser.add_argument("--execution", action="append", choices=("local", "worker"), default=[])
    args = parser.parse_args(argv)
    run_all = not (args.score_only or args.categories or args.legacy_replay or args.execution)
    if run_all or args.score_only:
        score_gate()
        print("score-v1: ok")
    if run_all or args.categories:
        categories_gate()
        print("categories: ok")
    if run_all or args.legacy_replay:
        legacy_gate(fail_on_unmapped=args.fail_on_unmapped)
        print("legacy-replay: ok")
    if run_all or args.execution:
        asyncio.run(execution_gate(args.execution or ["local", "worker"]))
        print("execution: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
