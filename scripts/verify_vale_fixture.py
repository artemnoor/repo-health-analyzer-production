"""Run the read-only Vale before/after verification for a repository fixture.

This script is operational verification only. It does not provision Vale, add
the binary to the repository, or change the target checkout.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _run_process(
    *,
    executable: str | Path,
    args: tuple[str, ...],
    cwd: Path,
    tool_id: str,
    timeout: float = 120.0,
):
    from repowise.core.analysis.analyzer_integration.process import (
        ProcessRequest,
        SubprocessProcess,
    )

    return SubprocessProcess().run(
        ProcessRequest(
            tool_id=tool_id,
            executable=executable,
            args=args,
            cwd=cwd,
            timeout=timeout,
            output_cap=16 * 1024 * 1024,
            repository_id="vale-live-verification",
            phase="verification",
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        type=Path,
        default=ROOT / "spikes/_fixture/codex-external-audit-public-20260916",
    )
    parser.add_argument(
        "--vale",
        type=Path,
        default=ROOT / "spikes/documentation/vale/runs/vale-3.22.0/vale.exe",
    )
    parser.add_argument("--output", type=Path, help="Optional machine-readable evidence path")
    return parser


def _json_model(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _live_findings(adapter, context, policy) -> list[dict[str, Any]]:
    """Collect bounded raw matches for the local verification record only."""
    from repowise.core.analysis.health.integrations.vale_adapter import (
        batch_documentation_files,
        discover_documentation_files,
        parse_diagnostics,
        resolve_vale_executable,
    )

    files = discover_documentation_files(context.repo_path, policy, context.inventory)
    resolution = resolve_vale_executable(context, policy)
    if resolution.path is None:
        return []
    findings = []
    for batch in batch_documentation_files(
        files,
        config_path=policy.config_file,
        max_files=policy.max_files_per_batch,
        max_command_bytes=policy.max_command_bytes,
    ):
        output = adapter._run_process(
            context,
            resolution.path,
            (
                f"--config={policy.config_file}",
                f"--output={policy.policy.get('output_format') or 'JSON'}",
                *batch,
            ),
            phase="verification-diagnostics",
            timeout=min(policy.timeout_seconds, 115.0),
            output_cap=policy.output_cap_bytes,
        )
        if output.exit_code is None or output.timed_out or output.truncated:
            continue
        try:
            parsed = parse_diagnostics(json.loads(output.stdout), context.repo_path)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        findings.extend(
            {
                "file": item.file,
                "rule": item.rule,
                "severity": item.severity,
                "message": item.message,
                "line": item.line,
                "match": item.match,
                "finding_id": item.finding_id,
            }
            for item in parsed
        )
    return findings


def main() -> int:
    args = _parser().parse_args()
    repository = args.repository.resolve()
    vale = args.vale.resolve()
    if not repository.is_dir():
        raise SystemExit(f"repository does not exist: {repository}")
    if not vale.is_file():
        raise SystemExit(f"Vale executable does not exist: {vale}")

    from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext
    from repowise.core.analysis.health.integrations.native_adapters import parse_repohealth
    from repowise.core.analysis.health.integrations.vale_adapter import (
        ValeAdapter,
        load_vale_policy,
    )

    compose_health_score = importlib.import_module(
        "repowise.core.analysis.health.composite"
    ).compose_health_score

    version_output = _run_process(
        executable=vale,
        args=("--version",),
        cwd=repository,
        tool_id="vale.documentation",
        timeout=15.0,
    )
    if version_output.exit_code != 0:
        raise SystemExit(f"Vale version probe failed: {version_output.exit_code}")

    context = AnalyzerContext(
        repo_path=repository,
        repo_id="artem03102006/codex-external-audit-public-20260916",
        head_sha="live-verification",
        as_of_ts=datetime.now(UTC),
        capabilities=("local_scan",),
        tool_paths={"vale": str(vale)},
    )
    baseline_completed = subprocess.run(
        ["go", "run", "./cmd/repohealth", str(repository), "--format", "json"],
        cwd=ROOT / "vendor/repohealth",
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if baseline_completed.returncode != 0:
        raise SystemExit(
            f"RepoHealth baseline failed: {baseline_completed.returncode}: "
            f"{baseline_completed.stderr[:500]}"
        )

    baseline_payload = json.loads(baseline_completed.stdout)
    baseline = parse_repohealth(baseline_payload, context, raw_ref="native://repohealth/live")
    adapter = ValeAdapter(project_root=ROOT)
    policy = load_vale_policy(ROOT)
    vale_result = adapter.run(context)
    before = compose_health_score((baseline,), repository_id=context.repo_id)
    after = compose_health_score((baseline, vale_result), repository_id=context.repo_id)

    record = {
        "target": str(repository),
        "vale": {
            "executable": str(vale),
            "version_output": version_output.stdout.strip(),
            "validated_version": policy.tool_version,
            "policy_revision": policy.revision,
            "policy_digest": policy.digest,
            "source_commit": vale_result.source_versions.get("vale_source_commit"),
        },
        "baseline": {
            "cli_score": baseline_payload.get("score"),
            "docs_category": next(
                item
                for item in baseline_payload.get("categories", [])
                if item.get("name") == "docs"
            ),
            "result": _json_model(baseline),
        },
        "vale_result": _json_model(vale_result),
        "vale_findings_local": _live_findings(adapter, context, policy),
        "composition": {
            "before": _json_model(before),
            "after": _json_model(after),
            "docs_delta": (after.dimensions["docs"] or 0.0) - (before.dimensions["docs"] or 0.0),
            "overall_delta": (after.overall or 0.0) - (before.overall or 0.0),
        },
    }
    serialized = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
        print(f"Vale before/after evidence: {args.output.resolve()}")
        print(
            f"findings={len(record['vale_findings_local'])} "
            f"docs_delta={record['composition']['docs_delta']:.4f} "
            f"overall_delta={record['composition']['overall_delta']:.4f}"
        )
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
