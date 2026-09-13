"""CLI entry point for bounded repository-health batches.

The command deliberately uses the same ingestion primitives as ``repowise
health`` and delegates execution to :class:`HealthOrchestrator`.  It is a
small batch surface, not a second analyzer implementation.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Any

import click

from repowise.cli._setup import configure_cli_logging
from repowise.cli.helpers import (
    console,
    err_console,
    load_config,
    load_state,
    resolve_command_target,
    run_async,
    silence_logs_for_machine_output,
)
from repowise.core.analysis.health.integrations import AnalyzerContext
from repowise.core.analysis.health.integrations.orchestrator import HealthOrchestrator

MAX_HEALTH_FILES = 50_000
MAX_HEALTH_COMMITS = 10_000


def _head_sha(repo_path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "working-tree"
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "working-tree"


def _languages(parsed_files: list[Any]) -> tuple[str, ...]:
    values = {
        str(getattr(getattr(item, "file_info", None), "language", "") or "").lower()
        for item in parsed_files
    }
    return tuple(sorted(value for value in values if value))


def build_health_context(repo_path: Path, *, mode: str, scope: str) -> AnalyzerContext:
    """Build the reusable local inventory needed by registered analyzers."""
    from repowise.core.analysis.health.integrations.repowise_adapter import RepoWiseAdapter
    from repowise.core.ingestion import (
        ASTParser,
        FileTraverser,
        GraphBuilder,
        wire_tsconfig_resolver,
    )
    from repowise.core.ingestion.git_indexer import GitIndexer

    state = load_state(repo_path)
    config = load_config(repo_path)
    traverser = FileTraverser(
        repo_path,
        include_submodules=bool(state.get("include_submodules", False)),
        include_nested_repos=bool(state.get("include_nested_repos", False)),
        extra_exclude_patterns=list(config.get("exclude_patterns") or []) or None,
    )
    parser = ASTParser()
    graph_builder = GraphBuilder(repo_path)
    parsed_files: list[Any] = []
    for file_info in islice(traverser.traverse(), MAX_HEALTH_FILES):
        try:
            source = Path(file_info.abs_path).read_bytes()
            parsed = parser.parse_file(file_info, source)
            graph_builder.add_file(parsed)
            parsed_files.append(parsed)
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    wire_tsconfig_resolver(graph_builder, repo_path)
    graph_builder.build()

    git_meta_map: dict[str, dict[str, Any]] = {}
    if (repo_path / ".git").exists():
        try:
            _, metadata = run_async(
                GitIndexer(
                    repo_path,
                    tier=RepoWiseAdapter.git_tier(mode),
                    commit_limit=MAX_HEALTH_COMMITS,
                ).index_repo(str(repo_path))
            )
            git_meta_map = {
                str(item["file_path"]): item
                for item in metadata
                if item.get("file_path")
            }
        except (OSError, RuntimeError, ValueError):
            git_meta_map = {}

    capabilities = ["local_scan"]
    if (repo_path / ".git").exists():
        capabilities.append("git")
    return AnalyzerContext(
        repo_path=repo_path,
        repo_id=str(repo_path.resolve()),
        head_sha=_head_sha(repo_path),
        as_of_ts=datetime.now(UTC),
        scope=scope,
        mode=mode,
        inventory={
            "graph": graph_builder.graph(),
            "parsed_files": parsed_files,
            "git_meta_map": git_meta_map,
            "languages": _languages(parsed_files),
            "health_config": {},
            "exclude_patterns": list(config.get("exclude_patterns") or []),
            "duplication_cache_dir": repo_path / ".repowise",
            "health_caps": {
                "max_files": MAX_HEALTH_FILES,
                "max_commits": MAX_HEALTH_COMMITS,
                "max_report_bytes": 67_108_864,
            },
        },
        capabilities=tuple(capabilities),
        config_digest=str(config.get("digest") or "") or None,
        cache_dir=repo_path / ".repowise" / "cache",
    )


def execute_health_batch(
    contexts: list[AnalyzerContext],
    *,
    concurrency: int,
    retries: int,
    resume: bool,
    dry_run: bool,
    analyzers: list[str] | None = None,
) -> Any:
    """Synchronous embedding helper used by Click and automation."""
    orchestrator = HealthOrchestrator(max_concurrency=concurrency, max_retries=retries)
    return run_async(
        orchestrator.run_batch(
            contexts,
            selected_analyzers=analyzers,
            resume=resume,
            dry_run=dry_run,
        )
    )


@click.command("health-batch")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--all", "all_repositories", is_flag=True, help="Run every repository in the detected workspace.")
@click.option("--workspace", is_flag=True, help="Resolve targets from the surrounding workspace.")
@click.option("--concurrency", type=click.IntRange(min=1, max=32), default=2, show_default=True)
@click.option("--retries", type=click.IntRange(min=0, max=5), default=1, show_default=True)
@click.option("--resume", is_flag=True, help="Resume the last incomplete health phase for each repository.")
@click.option("--dry-run", is_flag=True, help="Plan targets and analyzers without running tools.")
@click.option("--mode", "health_mode", type=click.Choice(["fast", "full", "offline", "diff", "backfill"]), default="fast", show_default=True)
@click.option("--scope", default="all", show_default=True)
@click.option("--analyzers", default=None, help="Comma-separated analyzer IDs; defaults to all registered analyzers.")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table", show_default=True)
@click.option("--verbose", "verbose", is_flag=True, help="Show debug logs from the batch runtime.")
def health_batch_command(
    paths: tuple[Path, ...],
    all_repositories: bool,
    workspace: bool,
    concurrency: int,
    retries: int,
    resume: bool,
    dry_run: bool,
    health_mode: str,
    scope: str,
    analyzers: str | None,
    fmt: str,
    verbose: bool,
) -> None:
    """Run health analyzers for one or more repositories with bounded concurrency."""
    configure_cli_logging(verbose=verbose)
    if fmt == "json":
        silence_logs_for_machine_output()
    status = err_console if fmt == "json" else console
    if all_repositories and paths:
        raise click.UsageError("--all cannot be combined with explicit repository paths")
    target = resolve_command_target(path=str(paths[0]) if paths else None, workspace_flag=workspace)
    target.notice(status, command="health-batch")

    targets = list(paths)
    if all_repositories or (target.is_workspace and not paths):
        if target.ws_config is None or target.ws_root is None:
            raise click.ClickException("No workspace repositories were found")
        targets = [
            (target.ws_root / entry.path).resolve()
            for entry in target.ws_config.repos
            if target.repo_filter is None or entry.alias == target.repo_filter
        ]
    elif not targets:
        if target.repo_path is None:
            raise click.ClickException("Provide repository paths or use --all in a workspace")
        targets = [target.repo_path]

    if not targets:
        raise click.ClickException("No repositories selected")
    contexts = [build_health_context(path.resolve(), mode=health_mode, scope=scope) for path in targets]
    selected = [item.strip() for item in analyzers.split(",") if item.strip()] if analyzers else None
    batch = execute_health_batch(
        contexts,
        concurrency=concurrency,
        retries=retries,
        resume=resume,
        dry_run=dry_run,
        analyzers=selected,
    )
    rows = [
        {
            "repository_id": outcome.repository_id,
            "status": outcome.status,
            "phase": outcome.phase,
            "score": outcome.score.overall if outcome.score else None,
            "coverage": outcome.score.coverage if outcome.score else None,
            "planned_analyzers": list(outcome.planned_analyzers),
            "error": outcome.error,
        }
        for outcome in batch.outcomes
    ]
    payload = {
        "repositories": rows,
        "summary": {
            "total": len(rows),
            "completed": batch.completed,
            "failed": batch.failed,
            "skipped": batch.skipped,
            "duration_ms": batch.duration_ms,
            "max_concurrency": batch.max_concurrency,
        },
    }
    if fmt == "json":
        click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    for row in rows:
        status.print(
            f"{row['repository_id']}  {row['status']}  "
            f"score={row['score'] if row['score'] is not None else '—'}  "
            f"coverage={row['coverage'] if row['coverage'] is not None else '—'}"
        )
    status.print(
        f"[bold]health-batch[/bold] — {batch.completed} completed, "
        f"{batch.failed} failed, {batch.skipped} skipped"
    )


__all__ = ["build_health_context", "execute_health_batch", "health_batch_command"]
