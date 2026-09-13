"""``repowise health`` Click command + single-repo orchestration.

Mirrors the dead-code CLI: ingest → analyze → render. Reads from
``HealthFileMetric`` / ``HealthFinding`` if a fresh index exists, falls
back to a live in-process analysis when run outside an indexed repo.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.table import Table

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
from repowise.core.analysis.health.counts import (
    COUNTS,
    DEFAULT_COUNTS,
    parse_counts,
)
from repowise.core.analysis.health.counts import (
    project as project_counts,
)
from repowise.core.analysis.health.models import split_by_origin
from repowise.core.analysis.health.scope import DEFAULT_SCOPE, SCOPES, parse_scope
from repowise.core.analysis.health.scoring import compute_kpis

from .codegen import _generate_refactoring_code
from .persist import (
    _load_canonical_health,
    _load_persisted_coverage_map,
    _load_recommendations,
    _persist_health,
)
from .refactoring_targets import _render_refactoring_targets
from .summary import (
    _render_badge,
    _render_canonical_score,
    _render_composition_line,
    _render_defect_accuracy_line,
    _render_distribution_line,
    _render_performance_section,
    _render_split_line,
    canonical_score_label,
    canonical_score_markdown,
)
from .trends import _render_trend


@click.command("health")
@click.argument("path", required=False, type=click.Path(exists=True))
@click.option(
    "--file",
    "file_filter",
    default=None,
    help="Deep-dive a single file (relative path).",
)
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["table", "json", "md"]),
    help="Output format.",
)
@click.option(
    "--repo",
    "repo_alias",
    default=None,
    help="Workspace repo alias to analyze.",
)
@click.option(
    "--no-workspace",
    is_flag=True,
    default=False,
    help="Force single-repo mode.",
)
@click.option(
    "--refactoring-targets",
    "refactoring_targets",
    is_flag=True,
    default=False,
    help="Print top refactoring candidates (impact/effort ratio).",
)
@click.option(
    "--generate-code",
    "generate_code",
    default=None,
    metavar="SELECTOR",
    help=(
        "Opt-in: generate refactored code + a diff for one suggestion via the "
        "configured LLM. SELECTOR is a 1-based rank (e.g. 1) or a target-symbol "
        "match. Reuses the repo's provider/model; requires an API key."
    ),
)
@click.option(
    "--module",
    "module_filter",
    default=None,
    help="Restrict the report to files whose path starts with this prefix.",
)
@click.option(
    "--dimension",
    "dimension_filter",
    default=None,
    help="Filter persisted health facts by dimension (for example security or performance).",
)
@click.option(
    "--subject",
    "subject_filter",
    default=None,
    help="Filter persisted findings/recommendations by subject text.",
)
@click.option(
    "--explain",
    "explain_view",
    is_flag=True,
    default=False,
    help=(
        "Show persisted snapshot status, evidence coverage and limitations; "
        "the repository score is 0–100 while file KPIs remain 0–10."
    ),
)
@click.option(
    "--scope",
    default=DEFAULT_SCOPE,
    type=click.Choice(list(SCOPES)),
    help=(
        "Which files to report on. Tests score higher than production code, "
        "so 'production' lowers every figure without a defect being found."
    ),
)
@click.option(
    "--counts",
    default=DEFAULT_COUNTS,
    type=click.Choice(list(COUNTS)),
    help=(
        "What the score counts. 'code_shape' removes the git-derived half, "
        "which rises as a file is worked on rather than describing its code."
    ),
)
@click.option(
    "--trend",
    "trend_view",
    is_flag=True,
    default=False,
    help="Print the last 10 health snapshots from the SQLite history.",
)
@click.option(
    "--badge",
    "badge_view",
    is_flag=True,
    default=False,
    help="Print a ready-to-paste health badge (Markdown) for this repo's README.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Show debug logs from the pipeline.",
)
@click.option(
    "--health-mode",
    "--mode",
    "health_mode",
    default="full",
    type=click.Choice(["fast", "full", "offline", "diff", "backfill"]),
    show_default=True,
    help="Analyzer depth: fast/offline, full, diff/PR or backfill.",
)
@click.option(
    "--as-of",
    "as_of",
    default=None,
    help="Replay timestamp (ISO-8601); defaults to the current UTC timestamp.",
)
@click.option(
    "--analyzers",
    default=None,
    help="Comma-separated analyzer IDs to run; defaults to the registered set.",
)
def health_command(
    path: str | None,
    file_filter: str | None,
    fmt: str,
    repo_alias: str | None,
    no_workspace: bool,
    refactoring_targets: bool,
    generate_code: str | None,
    module_filter: str | None,
    dimension_filter: str | None,
    subject_filter: str | None,
    explain_view: bool,
    scope: str,
    counts: str,
    trend_view: bool,
    badge_view: bool,
    verbose: bool,
    health_mode: str,
    as_of: str | None,
    analyzers: str | None,
) -> None:
    """Compute code-health scores from markers (CCN, nesting, brain-method).

    Runs in-process — no LLM, no network. Re-uses the repowise ingestion
    parser, graph builder, and git indexer.
    """
    configure_cli_logging(verbose=verbose)

    from pathlib import Path as PathlibPath

    from repowise.core.ingestion import ASTParser, FileTraverser, GraphBuilder

    # Silence structlog/stdlib info+debug lines when the user asked for a
    # machine-readable format so stdout is pure JSON/Markdown and safe to
    # pipe into jq or other tools (e.g. `repowise health --format json | jq .kpis`).
    if fmt != "table":
        silence_logs_for_machine_output()

    from repowise.core.analysis.health.integrations import AnalyzerContext, registry
    from repowise.core.analysis.health.integrations.repowise_adapter import register_repowise

    # Status output goes to stderr when the user asked for a machine-readable
    # format — otherwise rich's banner pollutes stdout and breaks
    # `repowise health --format json | jq …` (and the CI smoke test).
    status = err_console if fmt != "table" else console

    target = resolve_command_target(
        path=path, no_workspace_flag=no_workspace, repo_alias=repo_alias
    )
    target.notice(status, command="health")

    if target.is_workspace:
        if target.repo_filter is not None:
            picked = target.resolve_repo_alias(target.repo_filter)
            if picked is None:
                raise click.ClickException(f"Unknown repo alias: {target.repo_filter}")
            repo_path = picked
        else:
            primary = target.primary_path()
            if primary is None:
                raise click.ClickException("Workspace has no primary repo configured.")
            repo_path = primary
    else:
        assert target.repo_path is not None
        repo_path = target.repo_path

    status.print(f"[bold]repowise health[/bold] — {repo_path}")

    if trend_view:
        # The trend reads stored snapshots, which carry the calibrated score
        # only. Saying so beats printing a projected headline's flag over an
        # unprojected line.
        if parse_scope(scope) != DEFAULT_SCOPE or parse_counts(counts) != DEFAULT_COUNTS:
            status.print(
                "[dim]The trend reads stored snapshots, so --scope and --counts "
                "do not apply to it.[/dim]"
            )
        _render_trend(repo_path, fmt=fmt)
        return

    # Analyze the same file set that was indexed: a repo initialized with
    # --include-submodules persists the flag in state.json, and a flagless
    # traverser here would silently score a different (smaller) tree.
    state = load_state(repo_path)
    include_submodules = bool(state.get("include_submodules", False))
    include_nested_repos = bool(state.get("include_nested_repos", False))
    # `repowise health` persists metrics into the same rows the indexer writes,
    # so it has to analyze the same file set. Without the config's exclude
    # patterns it scored — and overwrote rows for — files the index had
    # deliberately dropped, and on a repo excluding a manifest directory it
    # could write a different `module` than the index did.
    exclude_patterns: list[str] = list(load_config(repo_path).get("exclude_patterns") or [])

    traverser = FileTraverser(
        repo_path,
        include_submodules=include_submodules,
        include_nested_repos=include_nested_repos,
        extra_exclude_patterns=exclude_patterns or None,
    )
    file_infos = list(traverser.traverse())
    parser = ASTParser()
    graph_builder = GraphBuilder(
        repo_path,
        include_submodules=include_submodules,
        include_nested_repos=include_nested_repos,
    )

    parsed_files = []
    for fi in file_infos:
        try:
            source = PathlibPath(fi.abs_path).read_bytes()
            parsed = parser.parse_file(fi, source)
            graph_builder.add_file(parsed)
            parsed_files.append(parsed)
        except Exception:
            continue

    from repowise.core.ingestion import wire_tsconfig_resolver

    wire_tsconfig_resolver(
        graph_builder,
        repo_path,
        include_submodules=include_submodules,
        include_nested_repos=include_nested_repos,
    )
    graph_builder.build()

    adapter = register_repowise(registry)
    git_meta_map: dict = {}
    try:
        from repowise.core.ingestion.git_indexer import GitIndexer

        git_indexer = GitIndexer(repo_path, tier=adapter.git_tier(health_mode))
        _, metadata_list = run_async(git_indexer.index_repo(str(repo_path)))
        git_meta_map = {m["file_path"]: m for m in metadata_list}
    except Exception:
        pass

    # Coverage folds into scoring from whatever `repowise coverage add` (or
    # index-time ingest) persisted - no per-run flag. Ingestion lives solely
    # in the `coverage` command group.
    coverage_map = _load_persisted_coverage_map(repo_path)

    # Load any .repowise/health-rules.json the user keeps in the repo.
    from repowise.core.analysis.health.config import HealthConfig

    health_cfg = HealthConfig.load(repo_path)
    analyzer_cfg = (
        health_cfg.to_analyzer_config([pf.file_info.path for pf in parsed_files])
        if (health_cfg.disabled_biomarkers or health_cfg.rules)
        else None
    )
    if as_of is None:
        as_of_ts = datetime.now(UTC)
    else:
        try:
            as_of_ts = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            if as_of_ts.tzinfo is None:
                as_of_ts = as_of_ts.replace(tzinfo=UTC)
            as_of_ts = as_of_ts.astimezone(UTC)
        except ValueError as exc:
            raise click.ClickException(f"Invalid --as-of timestamp: {as_of}") from exc

    changed_files: set[str] = set()
    if health_mode == "diff":
        for diff_args in (("diff", "--name-only"), ("diff", "--name-only", "HEAD~1", "HEAD")):
            try:
                diff = subprocess.run(
                    ["git", *diff_args],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            changed_files.update(
                line.strip().replace("\\", "/") for line in diff.stdout.splitlines() if line.strip()
            )
            if changed_files:
                break

    from repowise.core.workspace.update import get_head_commit

    capabilities = ("local_scan",)
    if (Path(repo_path) / ".git").exists():
        capabilities += ("git",)
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "vendor" / "SOURCES.lock").is_file():
        root = root.parent
    for tool_id, filenames in {
        "scorecard": ("scorecard.exe", "scorecard"),
        "repohealth": ("repohealth.exe", "repohealth"),
        "criticality-score": ("criticality-score.exe", "criticality-score"),
    }.items():
        if any((root / "bin" / filename).is_file() for filename in filenames):
            capabilities += (f"tool:{tool_id}",)

    context = AnalyzerContext(
        repo_path=Path(repo_path),
        repo_id=str(Path(repo_path).resolve()),
        head_sha=get_head_commit(Path(repo_path)) or "working-tree",
        as_of_ts=as_of_ts,
        scope=scope,
        mode=health_mode,
        inventory={
            "graph": graph_builder.graph(),
            "parsed_files": parsed_files,
            "coverage_map": coverage_map,
            "git_meta_map": git_meta_map,
            "health_config": analyzer_cfg or {},
            "exclude_patterns": exclude_patterns,
            "duplication_cache_dir": Path(repo_path) / ".repowise",
            "changed_files": changed_files,
        },
        capabilities=capabilities,
    )
    planned = registry.plan(context)
    if analyzers:
        requested = {item.strip() for item in analyzers.split(",") if item.strip()}
        known = {item.definition.id for item in planned}
        unknown = requested - known
        if unknown:
            raise click.ClickException(f"Unknown analyzer IDs: {', '.join(sorted(unknown))}")
        planned = tuple(item for item in planned if item.definition.id in requested)
    if not planned:
        raise click.ClickException("No analyzers selected")
    results = tuple(registry.run(item, context) for item in planned)
    composition = next(
        (result for result in results if result.analyzer_id == "repowise.health"),
        results[0],
    )
    report = adapter.last_report
    if report is None:
        raise click.ClickException(
            f"Analyzer {planned[0].definition.id} did not produce a legacy report"
        )

    # Persist health to the repo's wiki.db so the dashboard, MCP tools, and
    # `repowise status` see the same numbers as this CLI run.
    #
    # Skip when fmt != "table" (json/md are read by scripts and CI; side
    # effects are unwelcome) or when the run is filtered to a single
    # file/module (those are inspection runs that shouldn't overwrite
    # repo-level state).
    if fmt == "table" and not file_filter and not module_filter:
        _persist_health(
            repo_path,
            report=report,
            envelope=composition,
            context=context,
            analyzer_results=results,
        )

    # Read back the committed canonical rows for explain/filter semantics. The
    # analyzer output above remains the CLI's familiar table shape; this read
    # is what makes the new controls operate on durable facts, not on a second
    # in-memory scoring implementation.
    canonical_projection = None
    if not file_filter and not module_filter:
        canonical_projection = _load_canonical_health(
            repo_path,
            scope=parse_scope(scope),
            dimension=dimension_filter,
            subject=subject_filter,
            include_evidence=explain_view,
        )

    metrics = report.metrics
    if file_filter:
        metrics = [m for m in metrics if m.file_path == file_filter]
    if module_filter:
        metrics = [m for m in metrics if m.file_path.startswith(module_filter)]
    if dimension_filter:
        if dimension_filter == "maintainability":
            metrics = [m for m in metrics if getattr(m, "maintainability_score", None) is not None]
        elif dimension_filter == "performance":
            metrics = [m for m in metrics if getattr(m, "performance_score", None) is not None]
    narrowed = parse_scope(scope) == "production"
    if narrowed:
        metrics = [m for m in metrics if not m.is_test]
    # Taken before the projection, so a row the projection cannot read still
    # keeps its findings rather than reading as a file that left the repo.
    scoped_paths = {m.file_path for m in metrics}
    code_shape = parse_counts(counts) == "code_shape"
    if code_shape:
        # No `unscored` counterpart to the API's: this command scores live, so
        # every row carries the split the projection reads.
        metrics, _ = project_counts(counts, metrics)
    if narrowed or code_shape:
        # Every figure the controls select for. Defect accuracy below is not
        # one of them: it scores the ranking against `prior_defect`, and
        # narrowing leaves it no labels to be accurate about.
        report.kpis = compute_kpis(
            metrics, {p for p, m in git_meta_map.items() if m.get("is_hotspot")}
        )
    metrics_sorted = sorted(metrics, key=lambda m: m.score)

    findings = report.findings
    if file_filter:
        findings = [f for f in findings if f.file_path == file_filter]
    if module_filter:
        findings = [f for f in findings if f.file_path.startswith(module_filter)]
    if dimension_filter:
        findings = [
            f for f in findings if (getattr(f, "dimension", None) or "defect") == dimension_filter
        ]
    if subject_filter:
        needle = subject_filter.casefold()
        findings = [
            f
            for f in findings
            if needle
            in " ".join(
                str(value or "")
                for value in (
                    getattr(f, "file_path", None),
                    getattr(f, "function_name", None),
                    getattr(f, "reason", None),
                )
            ).casefold()
        ]
    if narrowed:
        findings = [f for f in findings if f.file_path in scoped_paths]
    if code_shape:
        # A history finding cannot explain a score the history half was taken
        # out of, so it is not part of this reading.
        findings = split_by_origin(findings)[0]

    if generate_code is not None:
        suggestions = getattr(report, "refactoring_suggestions", None) or []
        if file_filter:
            suggestions = [s for s in suggestions if s.file_path == file_filter]
        if module_filter:
            suggestions = [s for s in suggestions if s.file_path.startswith(module_filter)]
        # Attaches the same batched validation block the read surfaces emit;
        # code generation remains explicitly requested and never auto-applies.
        _load_recommendations(repo_path, suggestions, metrics_sorted)
        _generate_refactoring_code(repo_path, suggestions, generate_code, fmt=fmt)
        return

    if refactoring_targets:
        suggestions = getattr(report, "refactoring_suggestions", None) or []
        if file_filter:
            suggestions = [s for s in suggestions if s.file_path == file_filter]
        if module_filter:
            suggestions = [s for s in suggestions if s.file_path.startswith(module_filter)]
        recommendations = _load_recommendations(repo_path, suggestions, metrics_sorted)
        _render_refactoring_targets(metrics_sorted, findings, recommendations, fmt=fmt)
        return

    if badge_view:
        _render_badge(report.kpis.get("average_health"))
        return

    if fmt == "json":
        explain = None
        if explain_view:
            explain = (
                {
                    "read_model": canonical_projection["meta"]["read_model"],
                    "snapshot_id": canonical_projection["snapshot"]["id"],
                    "status": canonical_projection["snapshot"]["status"],
                    "canonical_repository_health": canonical_score_label(canonical_projection),
                    "canonical_score_scale": 100,
                    "score_recomputed": canonical_projection["meta"]["score_recomputed"],
                    "coverage": canonical_projection["coverage"],
                    "limitations": canonical_projection["limitations"],
                    "filters": canonical_projection["meta"]["filters"],
                }
                if canonical_projection
                else {
                    "read_model": "in_process_composition",
                    "score_recomputed": False,
                    "status": composition.status.value,
                    "canonical_repository_health": canonical_score_label(None),
                    "canonical_score_scale": 100,
                    "limitations": ["No persisted canonical snapshot available."],
                }
            )
        click.echo(
            json.dumps(
                {
                    "kpis": report.kpis,
                    "scope": parse_scope(scope),
                    "counts": parse_counts(counts),
                    "metrics": [
                        {
                            "file_path": m.file_path,
                            "score": m.score,
                            "max_ccn": m.max_ccn,
                            "max_nesting": m.max_nesting,
                            "nloc": m.nloc,
                            "has_test_file": m.has_test_file,
                            "line_coverage_pct": m.line_coverage_pct,
                            "branch_coverage_pct": m.branch_coverage_pct,
                            "duplication_pct": m.duplication_pct,
                        }
                        for m in metrics_sorted
                    ],
                    "findings": [
                        {
                            "biomarker_type": f.biomarker_type,
                            "severity": str(f.severity),
                            "file_path": f.file_path,
                            "function_name": f.function_name,
                            "health_impact": f.health_impact,
                            "details": f.details,
                            "reason": f.reason,
                        }
                        for f in findings
                    ],
                    "composition": composition.model_dump(mode="json"),
                    "analyzer_results": [result.model_dump(mode="json") for result in results],
                    **({"canonical": canonical_projection} if canonical_projection else {}),
                    **({"explain": explain} if explain is not None else {}),
                },
                indent=2,
            )
        )
        return

    if fmt == "md":
        click.echo("# Code Health Report\n")
        click.echo(f"- **composition_status**: {composition.status.value}")
        click.echo(f"- **composition_schema_version**: {composition.schema_version}")
        if explain_view:
            click.echo(canonical_score_markdown(canonical_projection))
            if canonical_projection:
                click.echo(f"- **canonical_snapshot**: {canonical_projection['snapshot']['id']}")
                click.echo(
                    f"- **evidence_coverage**: {canonical_projection['coverage']['evidence_coverage']}"
                )
                click.echo(f"- **limitations**: {len(canonical_projection['limitations'])}")
            else:
                click.echo("- **canonical_snapshot**: unavailable")
        for k, v in report.kpis.items():
            click.echo(f"- **{k}**: {v}")
        click.echo("\n## Findings\n")
        for f in findings:
            click.echo(
                f"- [{f.severity}] `{f.file_path}` {f.function_name or ''} "
                f"- {f.reason} (impact -{f.health_impact:.2f})"
            )
        return

    # Table format
    from repowise.core.analysis.health.grading import (
        BAND_LABEL,
        BAND_TERMINAL_COLOR,
        band_for,
    )
    from repowise.core.analysis.health.grading import (
        distribution as health_distribution,
    )

    kpis = report.kpis
    avg = kpis.get("average_health")
    band_str = ""
    if isinstance(avg, (int, float)):
        band = band_for(float(avg))
        band_color = BAND_TERMINAL_COLOR[band]
        band_str = f" [[{band_color}]{BAND_LABEL[band]}[/{band_color}]]"
    console.print(
        f"\nCode health: [bold]{avg if avg is not None else '?'}[/bold]/10{band_str} · "
        f"Hotspot: [bold]{kpis.get('hotspot_health', '?')}[/bold]/10 · "
        f"Worst: [bold]{kpis.get('worst_performer_score', '?')}[/bold]/10 "
        f"({kpis.get('worst_performer_path', 'n/a')})"
    )
    if code_shape:
        console.print("[dim]Counting code shape only — change history is left out.[/dim]")
    _render_split_line(kpis)
    _render_composition_line(composition)
    if explain_view:
        _render_canonical_score(canonical_projection)
        if canonical_projection:
            snapshot = canonical_projection["snapshot"]
            coverage = canonical_projection["coverage"]
            console.print(
                "[dim]Persisted snapshot:[/dim] "
                f"{snapshot['id']} · status={snapshot['status']} · "
                f"evidence={coverage['evidence_coverage']:.0%} · "
                f"unknown={snapshot['unknown_count']} · errors={snapshot['error_count']}"
            )
            if canonical_projection["limitations"]:
                console.print(
                    "[yellow]Limitations:[/yellow] "
                    + "; ".join(item["code"] for item in canonical_projection["limitations"])
                )
        else:
            console.print("[yellow]No persisted canonical snapshot available.[/yellow]")
    _render_distribution_line(health_distribution(metrics))

    _render_defect_accuracy_line(report)

    # Performance pillar section: lead with the finding COUNT + density +
    # coverage (the honest signal), not the bounded /10 average. Language comes
    # from the parsed files (the in-memory metrics don't carry it).
    _render_performance_section(
        report,
        {pf.file_info.path: pf.file_info.language for pf in parsed_files},
    )

    table = Table(title=f"Lowest-scoring files ({min(len(metrics_sorted), 20)})")
    table.add_column("File", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("CCN", justify="right")
    table.add_column("Nest", justify="right")
    table.add_column("NLOC", justify="right")
    table.add_column("Test?", justify="center")
    for m in metrics_sorted[:20]:
        score_color = BAND_TERMINAL_COLOR[band_for(m.score)]
        table.add_row(
            m.file_path,
            f"[{score_color}]{m.score:.1f}[/{score_color}]",
            str(m.max_ccn),
            str(m.max_nesting),
            str(m.nloc),
            "✓" if m.has_test_file else "—",
        )
    console.print(table)

    if findings:
        console.print(f"\n[bold]{len(findings)}[/bold] marker findings:")
        f_table = Table()
        f_table.add_column("Severity", style="magenta")
        f_table.add_column("Marker", style="cyan")
        f_table.add_column("File")
        f_table.add_column("Function")
        f_table.add_column("Impact", justify="right")
        for f in findings[:30]:
            f_table.add_row(
                str(f.severity),
                f.biomarker_type,
                f.file_path,
                f.function_name or "-",
                f"-{f.health_impact:.2f}",
            )
        console.print(f_table)
