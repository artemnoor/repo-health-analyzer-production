#!/usr/bin/env python3
"""Run the local, redacted verification gate for the Repository Health stack.

The gate intentionally checks semantics, not only process exit codes: pinned
source copies, native binaries, a clean migration, parser golden inputs,
append-only replay, rescore-without-collection and REST/MCP read-model parity.
It never prints raw source payloads or contributor/security details.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger("verify")
PACKAGE_PATHS = [
    ROOT / "packages" / "core" / "src",
    ROOT / "packages" / "server" / "src",
    ROOT / "packages" / "cli" / "src",
]
for package_path in reversed(PACKAGE_PATHS):
    sys.path.insert(0, str(package_path))


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )


def _run(
    label: str, command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    LOGGER.debug("command label=%s command=%s cwd=%s", label, command, cwd)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        bounded = (completed.stderr or completed.stdout)[-2000:]
        LOGGER.error("%s failed exit=%s detail=%s", label, completed.returncode, bounded)
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}")
    LOGGER.info("%s passed", label)


def _verify_sources() -> None:
    _run(
        "source-ledger",
        [sys.executable, str(ROOT / "scripts" / "vendor_sources.py"), "--verify"],
        cwd=ROOT,
    )


def _verify_binaries() -> None:
    required = ("scorecard", "repohealth", "criticality-score")
    missing = []
    for name in required:
        candidates = [ROOT / "bin" / f"{name}.exe", ROOT / "bin" / name]
        if not any(path.exists() for path in candidates):
            missing.append(name)
    if missing:
        raise RuntimeError(f"missing required native binaries: {', '.join(missing)}")
    LOGGER.info("native binaries passed count=%d", len(required))


def _verify_migration() -> None:
    with tempfile.TemporaryDirectory(prefix="repowise-health-verify-") as temp:
        database = (Path(temp) / "schema.db").as_posix()
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database}"
        env["PYTHONPATH"] = os.pathsep.join(
            [str(path) for path in PACKAGE_PATHS] + [env.get("PYTHONPATH", "")]
        )
        _run(
            "alembic-upgrade-head",
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(ROOT / "packages" / "core" / "alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=ROOT / "packages" / "core",
            env=env,
        )


def _native_golden_results():
    from repowise.core.analysis.health.integrations.contracts import AnalyzerContext
    from repowise.core.analysis.health.integrations.native_adapters import (
        parse_criticality_csv,
        parse_qlty,
        parse_repohealth,
        parse_scorecard,
        parse_sokrates,
    )

    fixtures = ROOT / "tests" / "fixtures" / "native"
    context = AnalyzerContext(
        repo_path=ROOT,
        repo_id="verification",
        head_sha="v" * 40,
        as_of_ts=datetime(2026, 9, 10, tzinfo=UTC),
        capabilities=["local_scan"],
    )
    results = (
        parse_scorecard(json.loads((fixtures / "scorecard" / "sample.json").read_text()), context),
        parse_repohealth(
            json.loads((fixtures / "repohealth" / "sample.json").read_text()), context
        ),
        parse_criticality_csv((fixtures / "criticality" / "sample.csv").read_text(), context),
        parse_qlty(json.loads((fixtures / "qlty" / "sarif.json").read_text()), context),
        parse_sokrates(
            json.loads((fixtures / "sokrates" / "sample-export.json").read_text()), context
        ),
    )
    if results[1].score != 78 or results[2].score is not None:
        raise AssertionError("native golden score/criticality invariant failed")
    if not results[3].findings or not results[4].metrics:
        raise AssertionError("native golden output lost findings or metrics")
    LOGGER.info("native golden passed analyzers=%d", len(results))
    return context, results


async def _verify_persistence_and_projection(context, results) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from repowise.core.analysis.health.integrations.contracts import AnalyzerContext
    from repowise.core.persistence import init_db
    from repowise.core.persistence.crud import (
        rescore_health_snapshot,
        save_health_envelope,
        upsert_repository,
    )
    from repowise.server.routers.code_health.canonical import build_canonical_health_report

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await init_db(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        repo = await upsert_repository(
            session,
            name="verification",
            local_path=str(ROOT),
            url="https://example.invalid/verification",
        )
        context = AnalyzerContext(
            repo_path=context.repo_path,
            repo_id=repo.id,
            head_sha=context.head_sha,
            as_of_ts=context.as_of_ts,
            scope=context.scope,
            mode=context.mode,
            capabilities=context.capabilities,
            inventory={"criticality": 0.4},
        )
        first = await save_health_envelope(session, repo.id, context, results)
        await session.commit()
        second = await save_health_envelope(session, repo.id, context, results)
        if first.id != second.id:
            raise AssertionError("replay key did not deduplicate snapshot")
        before_raw = await session.execute(text("SELECT COUNT(*) FROM health_raw_facts"))
        await rescore_health_snapshot(
            session,
            first.id,
            {"weights": {"scorecard:policy": 2}},
            score_config_digest="verify-score",
        )
        after_raw = await session.execute(text("SELECT COUNT(*) FROM health_raw_facts"))
        if before_raw.scalar_one() != after_raw.scalar_one():
            raise AssertionError("rescore changed raw fact count")
        report = await build_canonical_health_report(session, repo.id, snapshot_id=first.id)
        replay_report = await build_canonical_health_report(session, repo.id, snapshot_id=first.id)
        if report is None or replay_report is None:
            raise AssertionError("canonical projection missing")
        left = json.dumps(report, sort_keys=True, separators=(",", ":"))
        right = json.dumps(replay_report, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(left.encode()).hexdigest() != hashlib.sha256(right.encode()).hexdigest():
            raise AssertionError("canonical projection is not byte-stable")
        if not report["meta"]["score_recomputed"] or report["criticality"]["applied_to_score"]:
            raise AssertionError("rescore/criticality separation invariant failed")
    await engine.dispose()
    LOGGER.info("persistence/replay/projection passed")


def _verify_fixture() -> None:
    fixture = ROOT / "tests" / "fixtures" / "health" / "replay_repo"
    required = (
        fixture / "src" / "app.py",
        fixture / "tests" / "test_app.py",
        fixture / "generated" / "client.py",
        fixture / "vendor" / "third_party.py",
        fixture / "pyproject.toml",
        fixture / ".github" / "workflows" / "ci.yml",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"replay fixture is incomplete: {', '.join(missing)}")
    LOGGER.info("replay fixture passed files=%d", len(required))


def _verify_completion_surface() -> None:
    """Keep the composition gate aware of the public ranking surface."""
    required = (
        ROOT / "packages" / "server" / "src" / "repowise" / "server" / "routers" / "public_health.py",
        ROOT / "packages" / "web" / "src" / "app" / "ranking" / "page.tsx",
        ROOT / "packages" / "core" / "alembic" / "versions" / "0066_repository_health_ranking.py",
        ROOT / "scripts" / "verify_health_completion.py",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"health completion surface is incomplete: {', '.join(missing)}")
    LOGGER.info("health completion surface passed paths=%d", len(required))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="run the complete local gate")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    try:
        _verify_sources()
        _verify_binaries()
        _verify_fixture()
        _verify_completion_surface()
        _verify_migration()
        context, results = _native_golden_results()
        asyncio.run(_verify_persistence_and_projection(context, results))
    except Exception as exc:
        LOGGER.error("verification failed class=%s message=%s", type(exc).__name__, exc)
        return 1
    LOGGER.info("verification passed full=%s", args.full)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
