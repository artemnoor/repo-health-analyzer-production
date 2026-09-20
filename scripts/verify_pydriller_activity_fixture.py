"""Run the Activity/PyDriller composition against the audited local fixture."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "spikes" / "_fixture" / "codex-external-audit-public-20260916"
OUTPUT = ROOT / "spikes" / "activity" / "pydriller" / "runs" / "repo-health-activity.json"

from git import Repo  # noqa: E402

from repowise.core.analysis.analyzer_integration.contracts import AnalyzerContext  # noqa: E402
from repowise.core.analysis.health.integrations.chaoss_adapter import (  # noqa: E402
    CHAOSS_ACTIVITY_ID,
    ChaossAdapter,
    activity_adapter,
)
from repowise.core.analysis.health.integrations.pydriller_adapter import (  # noqa: E402
    PYDRILLER_POLICY_REVISION,
    PYDRILLER_SOURCE_COMMIT,
    GitActivityBaseline,
)


def _result_payload(result: Any) -> dict[str, Any]:
    return {
        "analyzer_id": result.analyzer_id,
        "analyzer_version": result.analyzer_version,
        "status": result.status.value,
        "score": result.score,
        "score_dimension": result.score_dimension,
        "metrics": [
            {
                "name": metric.name,
                "value": metric.value,
                "unit": metric.unit,
                "score": metric.score,
                "population": metric.population,
                "denominator": metric.denominator,
            }
            for metric in result.metrics
        ],
        "evidence": [
            {
                "source": ref.source,
                "source_commit": ref.source_commit,
                "tool_version": ref.tool_version,
                "json_pointer": ref.json_pointer,
                "confidence": ref.confidence,
                "redaction": ref.redaction,
            }
            for ref in result.evidence
        ],
        "limitations": [
            {
                "kind": limitation.kind,
                "reason": limitation.reason,
                "affected_scope": limitation.affected_scope,
            }
            for limitation in result.limitations
        ],
        "diagnostics": {
            key: value
            for key, value in result.diagnostics.items()
            if key != "as_of_ts"
        },
    }


def _context(
    repo: Repo,
    *,
    scope: str | None = None,
    baseline: GitActivityBaseline | None = None,
) -> AnalyzerContext:
    inventory: dict[str, Any] = {"default_branch": "main"}
    if scope:
        inventory["pydriller_scope"] = scope
    if baseline is not None:
        inventory["git_activity_baseline"] = baseline
    return AnalyzerContext(
        repo_path=FIXTURE,
        repo_id="artem03102006/codex-external-audit-public-20260916",
        head_sha=repo.head.commit.hexsha,
        as_of_ts=datetime(2026, 9, 16, 12, 1, tzinfo=UTC),
        inventory=inventory,
        capabilities=("chaoss:events", "git", "local_scan"),
    )


def main() -> None:
    repo = Repo(str(FIXTURE))
    default_hashes = frozenset(commit.hexsha for commit in repo.iter_commits("main"))
    baseline = GitActivityBaseline(
        source="existing.git-collector",
        commit_hashes=default_hashes,
        unique_commit_count=len(default_hashes),
    )
    base_context = _context(repo, baseline=baseline)
    before = ChaossAdapter().result(base_context, analyzer_id=CHAOSS_ACTIVITY_ID)
    after_default = activity_adapter(base_context)
    after_all_refs = activity_adapter(
        _context(repo, scope="all_refs_with_remotes", baseline=baseline)
    )
    default_diag = after_default.diagnostics["pydriller"]
    all_refs_diag = after_all_refs.diagnostics["pydriller"]
    report = {
        "verification": {
            "repository": "artem03102006/codex-external-audit-public-20260916",
            "fixture_commit_prefix": repo.head.commit.hexsha[:12],
            "as_of": base_context.as_of_ts.isoformat(),
            "policy": PYDRILLER_POLICY_REVISION,
            "tool_version": "2.12",
            "source_commit": PYDRILLER_SOURCE_COMMIT,
        },
        "before": _result_payload(before),
        "after_default_branch": _result_payload(after_default),
        "after_all_refs_with_remotes": _result_payload(after_all_refs),
        "comparison": {
            "before_score": before.score,
            "after_default_score": after_default.score,
            "after_all_refs_score": after_all_refs.score,
            "default_score_delta": (
                after_default.score - before.score
                if before.score is not None and after_default.score is not None
                else None
            ),
            "default_score_delta_reason": (
                "baseline Activity had no numeric score because no CollectOSS rows were supplied"
                if before.score is None
                else "numeric delta"
            ),
            "existing_git_unique_commits": len(default_hashes),
            "default_scope_unique_commits": default_diag["unique_commit_count"],
            "default_scope_overlap_commits": after_default.diagnostics["pydriller_overlap_commit_count"],
            "default_scope_new_commits": after_default.diagnostics["pydriller_new_commit_count"],
            "all_refs_unique_commits": all_refs_diag["unique_commit_count"],
            "all_refs_occurrences": all_refs_diag["commit_occurrence_count"],
            "all_refs_duplicate_occurrences": all_refs_diag["duplicate_commit_count"],
            "all_refs_overlap_commits": after_all_refs.diagnostics["pydriller_overlap_commit_count"],
            "all_refs_new_commits": after_all_refs.diagnostics["pydriller_new_commit_count"],
            "double_count_guard": after_default.diagnostics["double_count_guard"],
        },
        "evidence_summary": {
            "default_facts": {
                key: default_diag[key]
                for key in (
                    "execution_status",
                    "ref_scope",
                    "resolved_refs",
                    "unique_commit_count",
                    "duplicate_commit_count",
                    "unique_author_count",
                    "unique_committer_count",
                    "first_author_at",
                    "last_author_at",
                    "first_committer_at",
                    "last_committer_at",
                    "earliest_activity_at",
                    "latest_activity_at",
                    "total_additions",
                    "total_deletions",
                    "total_churn",
                    "modified_file_record_count",
                    "tracked_unique_file_count",
                    "merge_commit_count",
                    "empty_commit_count",
                    "active_period_count",
                    "observed_period_count",
                    "current_inactivity_days",
                    "longest_inactivity_days",
                    "latest_activity_age_days",
                    "meaningful_activity_ratio",
                    "windows",
                    "coverage",
                    "confidence",
                )
            },
            "all_refs_facts": {
                key: all_refs_diag[key]
                for key in (
                    "execution_status",
                    "ref_scope",
                    "resolved_refs",
                    "unique_commit_count",
                    "commit_occurrence_count",
                    "duplicate_commit_count",
                    "unique_author_count",
                    "total_additions",
                    "total_deletions",
                    "total_churn",
                    "coverage",
                    "confidence",
                )
            },
            "redaction": "No commit messages, emails, diffs, file lists, or fixture full hashes are emitted.",
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report["comparison"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
