"""Run the Code Health end-to-end verification on the SourceCraft fixture.

This harness is deliberately operational and read-only with respect to the
repository. It may start a temporary official ``sonarqube:community`` Docker
container, or use ``SONARQUBE_HOME``/``SONARQUBE_URL`` supplied by the caller.
Tokens and scanner logs are never written to the verification artifact.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY = ROOT / "spikes/_fixture/codex-external-audit-public-20260916"
DEFAULT_PROJECT = "repowise-code-health-live"
DEFAULT_URL = "http://127.0.0.1:9000"
log = structlog.get_logger("code_health.live_verification")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=DEFAULT_REPOSITORY)
    parser.add_argument("--sonar-url", default=os.environ.get("SONARQUBE_URL", DEFAULT_URL))
    parser.add_argument("--sonar-token", default=os.environ.get("SONARQUBE_TOKEN"))
    parser.add_argument("--scanner", type=Path, default=None)
    parser.add_argument("--scanner-docker", action="store_true", help="Run the official SonarSource scanner image")
    parser.add_argument("--scanner-image", default="sonarsource/sonar-scanner-cli:latest")
    parser.add_argument("--project-key", default=DEFAULT_PROJECT)
    parser.add_argument("--output", type=Path, default=ROOT / "spikes/code_health/runs/sourcecraft-live-code-health.json")
    parser.add_argument("--no-docker", action="store_true")
    parser.add_argument("--skip-scan", action="store_true", help="Use an already analyzed SonarQube project")
    return parser


def _run(command: list[str], *, cwd: Path | None = None, timeout: float = 120.0, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False)


def _wait_for_server(url: str, token: str, timeout: float = 180.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url.rstrip('/')}/api/system/status", auth=(token, ""), timeout=5.0)
            if response.is_success:
                status = response.json().get("status")
                if status == "UP":
                    return True
                if status not in {"STARTING", "DOWN", "MAINTENANCE"}:
                    return False
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(2)
    return False


def _docker_probe() -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        return {"available": False, "reason": "docker_executable_missing"}
    probe = _run([docker, "info"], timeout=10.0)
    if probe.returncode != 0:
        return {"available": False, "reason": "docker_engine_unavailable"}
    return {"available": True, "reason": None}


def _start_docker(url: str, *, probe: dict[str, Any] | None = None) -> str | None:
    del url
    if not (probe or _docker_probe()).get("available"):
        return None
    docker = shutil.which("docker")
    if not docker:
        return None
    name = f"repowise-code-health-{os.getpid()}"
    started = _run([docker, "run", "-d", "--name", name, "-p", "9000:9000", "sonarqube:community"], timeout=30.0)
    if started.returncode != 0:
        return None
    return name


def _git_head(repository: Path) -> str | None:
    completed = _run(["git", "rev-parse", "HEAD"], cwd=repository, timeout=15.0)
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value if re.fullmatch(r"[0-9a-fA-F]{7,64}", value) else None


def _start_standalone() -> subprocess.Popen[str] | None:
    home = os.environ.get("SONARQUBE_HOME")
    if not home:
        return None
    candidates = [
        Path(home) / "bin/windows-x86-64/StartSonar.bat",
        Path(home) / "bin/linux-x86-64/sonar.sh",
    ]
    launcher = next((path for path in candidates if path.is_file()), None)
    if launcher is None:
        return None
    if launcher.suffix.casefold() == ".bat":
        return subprocess.Popen(["cmd.exe", "/c", str(launcher)], cwd=launcher.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    return subprocess.Popen([str(launcher), "start"], cwd=launcher.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)


def _scanner_path(argument: Path | None) -> Path | None:
    if argument and argument.is_file():
        return argument
    for name in ("sonar-scanner", "sonar-scanner.bat", "sonar-scanner.cmd"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _run_scan(scanner: Path | None, repository: Path, url: str, token: str, project_key: str, *, docker_image: str | None = None) -> dict[str, Any]:
    properties = (
        "sonar.projectKey=" + project_key,
        "sonar.sources=.",
        "sonar.host.url=" + (url.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal") if docker_image else url),
        "sonar.token=" + token,
        "sonar.scm.disabled=true",
        "sonar.exclusions=**/.git/**,**/vendor/**,**/node_modules/**,**/dist/**,**/build/**",
    )
    if docker_image:
        docker = shutil.which("docker")
        if docker is None:
            raise RuntimeError("docker executable was not found for the official scanner image")
        command = [docker, "run", "--rm", "-v", f"{repository}:/usr/src", docker_image]
        for prop in properties:
            command.extend(("--define", prop))
    else:
        if scanner is None:
            raise RuntimeError("official sonar-scanner executable was not found")
        command = [str(scanner), *(f"-D{prop}" for prop in properties)]
    completed = _run(command, cwd=repository, timeout=600.0, env={**os.environ, "SONAR_TOKEN": token})
    # Scanner output is intentionally inspected in memory only; no logs are
    # persisted because command lines and verbose logs can contain credentials.
    output = completed.stdout + "\n" + completed.stderr
    task_match = re.search(r"(?:ceTaskId=|/api/ce/task\?id=)([A-Za-z0-9_-]+)", output)
    scanner_match = re.search(r"SonarScanner(?: CLI)?(?: version)?\s+([0-9][^\s/]*)", output, re.IGNORECASE)
    if completed.returncode != 0:
        raise RuntimeError(f"sonar-scanner failed with exit code {completed.returncode}")
    return {
        "exit_code": completed.returncode,
        "ce_task_id_present": task_match is not None,
        "ce_task_id": task_match.group(1) if task_match else None,
        "scanner_version": scanner_match.group(1) if scanner_match else None,
    }


def _wait_for_task(url: str, token: str, task_id: str | None) -> dict[str, Any]:
    if not task_id:
        return {"status": "UNKNOWN", "task_id_present": False}
    for _ in range(180):
        response = httpx.get(f"{url.rstrip('/')}/api/ce/task", params={"id": task_id}, auth=(token, ""), timeout=10.0)
        response.raise_for_status()
        task = response.json().get("task", {})
        status = task.get("status")
        if status in {"SUCCESS", "FAILED", "CANCELED"}:
            return {"status": status, "task_id_present": True}
        time.sleep(2)
    return {"status": "TIMEOUT", "task_id_present": True}


def _baseline(repository: Path, context: Any) -> Any:
    """Use the existing RepoHealth CLI baseline when it is available."""
    from repowise.core.analysis.health.integrations.native_adapters import parse_repohealth

    completed = _run(["go", "run", "./cmd/repohealth", str(repository), "--format", "json"], cwd=ROOT / "vendor/repohealth", timeout=180.0)
    if completed.returncode != 0:
        return None
    try:
        return parse_repohealth(json.loads(completed.stdout), context, raw_ref="native://repohealth/live")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def main() -> int:
    args = _parser().parse_args()
    repository = args.repository.resolve()
    if not repository.is_dir():
        raise SystemExit(f"repository does not exist: {repository}")
    token = args.sonar_token
    if not token:
        raise SystemExit("SONARQUBE_TOKEN or --sonar-token is required; it is never written to output")
    docker_name: str | None = None
    standalone: subprocess.Popen[str] | None = None
    docker_diagnostics: dict[str, Any] = {"attempted": False, "available": None, "reason": "not_attempted"}
    standalone_diagnostics: dict[str, Any] = {
        "configured": bool(os.environ.get("SONARQUBE_HOME")),
        "started": False,
        "reason": "not_attempted",
    }
    task: dict[str, Any] = {"status": "SKIPPED", "task_id_present": False}
    try:
        if not args.skip_scan and args.sonar_url == DEFAULT_URL and not args.no_docker:
            docker_probe = _docker_probe()
            docker_diagnostics = {"attempted": True, **docker_probe}
            docker_name = _start_docker(args.sonar_url, probe=docker_probe)
            if docker_name is None:
                standalone = _start_standalone()
                standalone_diagnostics["started"] = standalone is not None
                standalone_diagnostics["reason"] = None if standalone is not None else (
                    "not_configured" if not standalone_diagnostics["configured"] else "launcher_missing"
                )
        if not _wait_for_server(args.sonar_url, token):
            raise RuntimeError("SonarQube server did not become ready; Docker and standalone diagnostics are required")
        scanner = _scanner_path(args.scanner)
        scan = {"skipped": True}
        if not args.skip_scan:
            if scanner is None and not args.scanner_docker:
                raise RuntimeError("official sonar-scanner executable was not found")
            scan = _run_scan(
                scanner,
                repository,
                args.sonar_url,
                token,
                args.project_key,
                docker_image=args.scanner_image if args.scanner_docker else None,
            )
            task = _wait_for_task(args.sonar_url, token, scan.get("ce_task_id"))
            if task.get("status") != "SUCCESS":
                raise RuntimeError(f"SonarQube Compute Engine task did not succeed: {task.get('status')}")

        from repowise.core.analysis.analyzer_integration.contracts import (
            AnalyzerContext,
        )
        from repowise.core.analysis.health.integrations.code_health_analyzer import (
            CodeHealthAnalyzer,
        )
        from repowise.core.analysis.health.integrations.code_health_collector import (
            CodeHealthFactsCollector,
            CodeHealthSourcePorts,
        )
        from repowise.core.analysis.health.integrations.sonarqube_adapter import (
            SonarQubeHTTPTransport,
        )
        from repowise.core.ingestion.git_indexer import GitIndexer, GitIndexTier

        as_of = datetime.now(UTC)
        git_sizer = ROOT / "spikes/code_health/git-sizer/git-sizer.exe"
        if not git_sizer.is_file():
            discovered_git_sizer = shutil.which("git-sizer")
            git_sizer = Path(discovered_git_sizer) if discovered_git_sizer else None
        context = AnalyzerContext(
            repo_path=repository,
            repo_id="artem03102006/codex-external-audit-public-20260916",
            head_sha=_git_head(repository) or "unknown",
            as_of_ts=as_of,
            mode="full",
            capabilities=("local_scan", "git"),
            inventory={"sonarqube_project_key": args.project_key, "sonarqube_scanner_version": scan.get("scanner_version")},
            tool_paths={"git-sizer": str(git_sizer)} if git_sizer is not None else {},
        )
        git_indexer = GitIndexer(repository, tier=GitIndexTier.FULL)
        _, git_metadata = asyncio.run(git_indexer.index_repo(context.repo_id))
        git_meta_map = {
            str(item.get("file_path")): item
            for item in git_metadata
            if item.get("file_path")
        }
        context = context.model_copy(
            update={"inventory": {**context.inventory, "git_meta_map": git_meta_map}}
        )
        baseline = _baseline(repository, context)
        transport = SonarQubeHTTPTransport(args.sonar_url, token)
        facts = CodeHealthFactsCollector().collect(
            context,
            baseline,
            source_ports=CodeHealthSourcePorts(sonarqube_transport=transport),
        )
        result = CodeHealthAnalyzer().analyze(context, facts, baseline)
        sonar = facts.sonar
        git_structure = facts.git_structure
        todo = facts.todo_debt
        git_evidence = [
            {
                "subject": item.subject,
                "path": item.path,
                "pointer": item.json_pointer,
                "value": item.value,
            }
            for item in (git_structure.evidence if git_structure else ())
        ]
        result_evidence = [
            {
                "source": item.source,
                "path": item.path,
                "line": item.line_start,
                "pointer": item.json_pointer,
                "confidence": item.confidence,
            }
            for item in result.evidence
        ]
        record = {
            "repository": context.repo_id,
            "fixture": {"repository": context.repo_id, "head_sha": context.head_sha, "as_of": as_of.isoformat()},
            "operations": {"docker": docker_diagnostics, "standalone": standalone_diagnostics},
            "sonarqube": {
                "url": args.sonar_url,
                "project_key": args.project_key,
                "server_version": sonar.server_version if sonar else None,
                "scanner_version": sonar.scanner_version if sonar else scan.get("scanner_version"),
                "compute_engine": task,
                "api": {
                    "pages_fetched": sonar.pages_fetched if sonar else 0,
                    "pagination_complete": sonar.pagination_complete if sonar else None,
                },
                "scan": scan,
            },
            "baseline": {"available": baseline is not None, "status": baseline.status.value if baseline else None, "score": baseline.score if baseline else None},
            "facts": facts.summary(),
            "real_metrics": {
                "sonar": dict(sonar.measures) if sonar else {},
                "git_sizer": {
                    "metrics": dict(git_structure.metrics) if git_structure else {},
                    "level_of_concern": dict(git_structure.level_of_concern) if git_structure else {},
                    "evidence": git_evidence,
                },
                "todo": {
                    "loc": todo.included_loc,
                    "todo": todo.todo_count,
                    "fixme": todo.fixme_count,
                    "old": todo.old_count,
                    "old_ratio": todo.old_ratio,
                    "age_available": todo.diagnostics.get("age_available") if todo else None,
                    "history_source": todo.diagnostics.get("source") if todo else None,
                    "history_status": todo.status.value if todo else None,
                    "history_coverage": todo.coverage if todo else 0.0,
                    "history_confidence": todo.confidence if todo else 0.0,
                    "blame_files": todo.diagnostics.get("blame_files") if todo else None,
                    "marker_count": todo.diagnostics.get("marker_count") if todo else None,
                    "aged_marker_count": todo.diagnostics.get("aged_marker_count") if todo else None,
                    "hotspot_count": todo.hotspot_count if todo else 0,
                } if todo else {},
            },
            "result": {
                "status": result.status.value,
                "score": result.score,
                "coverage": facts.coverage,
                "confidence": facts.confidence,
                "score_before": baseline.score if baseline else None,
                "score_after": result.score,
                "baseline_metric_count": len(baseline.metrics) if baseline else 0,
                "baseline_score_bearing_metric_count": sum(1 for item in baseline.metrics if item.score is not None) if baseline else 0,
                "result_metric_count": len(result.metrics),
                "result_score_bearing_metric_count": sum(1 for item in result.metrics if item.score is not None),
                "components": result.diagnostics.get("code_health_components", {}),
                "double_counting_guard": result.diagnostics.get("double_counting_guard"),
            },
            "findings": [{"id": item.id, "subject": item.subject, "severity": item.severity, "reason": item.reason, "path": item.location.path if item.location else None, "line": item.location.line_start if item.location else None} for item in result.findings],
            "evidence": result_evidence,
            "secrets_redacted": True,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        log.info(
            "[FIX:live-report] artifact_written",
            repository=context.repo_id,
            status=result.status.value,
            finding_count=len(result.findings),
            score_before=baseline.score if baseline else None,
            score_after=result.score,
        )
        print(json.dumps({"output": str(args.output), "status": result.status.value, "score_before": baseline.score if baseline else None, "score_after": result.score, "findings": len(result.findings)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        log.error(
            "[FIX:live-report] verification_failed",
            repository="artem03102006/codex-external-audit-public-20260916",
            error_type=type(exc).__name__,
            docker=docker_diagnostics,
            standalone=standalone_diagnostics,
        )
        raise
    finally:
        if docker_name:
            docker = shutil.which("docker")
            if docker:
                _run([docker, "rm", "-f", docker_name], timeout=30.0)
        if standalone is not None and standalone.poll() is None:
            standalone.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
