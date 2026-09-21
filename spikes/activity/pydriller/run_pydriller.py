"""Run PyDriller against the SourceCraft audit fixture and emit JSON."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


def iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def safe_author(author: object) -> dict[str, str | None]:
    return {
        "name": getattr(author, "name", None),
        "email": getattr(author, "email", None),
        "username": getattr(author, "username", None),
    }


def run(repo_path: Path) -> dict[str, object]:
    from pydriller import Repository
    from pydriller.metrics.process.commits_count import CommitsCount
    from pydriller.metrics.process.contributors_count import ContributorsCount
    from pydriller.metrics.process.lines_count import LinesCount

    started = time.perf_counter()
    unique_by_hash: dict[str, dict[str, object]] = {}
    all_commit_count = 0
    all_modified = []
    for commit in Repository(
        str(repo_path),
        include_refs=True,
        include_remotes=True,
        order="date-order",
    ).traverse_commits():
        all_commit_count += 1
        if commit.hash in unique_by_hash:
            continue
        modifications = []
        for modification in commit.modified_files:
            modifications.append(
                {
                    "path": modification.new_path or modification.old_path,
                    "old_path": modification.old_path,
                    "change_type": modification.change_type.name,
                    "added_lines": modification.added_lines,
                    "deleted_lines": modification.deleted_lines,
                    "churn": modification.added_lines + modification.deleted_lines,
                    "diff_bytes": len((modification.diff or "").encode("utf-8", "ignore")),
                    "diff_preview": (modification.diff or "")[:600],
                }
            )
        all_modified.extend(modifications)
        inserted = sum(item["added_lines"] for item in modifications)
        deleted = sum(item["deleted_lines"] for item in modifications)
        unique_by_hash[commit.hash] = {
            "hash": commit.hash,
            "parents": list(commit.parents),
            "message": commit.msg,
            "author": safe_author(commit.author),
            "committer": safe_author(commit.committer),
            "author_date": commit.author_date,
            "committer_date": commit.committer_date,
            "merge": commit.merge,
            "empty_by_modified_files": len(modifications) == 0,
            "in_main_branch": commit.in_main_branch,
            "branches": sorted(commit.branches),
            "insertions": inserted,
            "deletions": deleted,
            "lines": inserted + deleted,
            "files": len(modifications),
            "modifications": modifications,
            "diff_preview": "\n".join(
                str(item.get("diff_preview", "")) for item in modifications[:1]
            )[:600],
        }

    unique = list(unique_by_hash.values())
    since = min(commit["author_date"] for commit in unique) - timedelta(seconds=1)
    until = max(commit["author_date"] for commit in unique) + timedelta(seconds=1)
    authors = Counter(
        (commit["author"]["email"] or commit["author"]["name"] or "<unknown>")
        for commit in unique
    )
    sample_commits = unique[:12]

    metric_errors: dict[str, str] = {}
    process_metrics: dict[str, object] = {}
    for name, factory in {
        "commits_count": lambda: CommitsCount(str(repo_path), since=since, to=until),
        "lines_count": lambda: LinesCount(str(repo_path), since=since, to=until),
        "contributors_count": lambda: ContributorsCount(str(repo_path), since=since, to=until),
    }.items():
        try:
            metric = factory()
            if name == "commits_count":
                process_metrics[name] = metric.count()
            elif name == "lines_count":
                process_metrics[name] = {
                    "changed": metric.count(),
                    "added": metric.count_added(),
                    "removed": metric.count_removed(),
                    "max_added": metric.max_added(),
                    "max_removed": metric.max_removed(),
                    "avg_added": metric.avg_added(),
                    "avg_removed": metric.avg_removed(),
                }
            else:
                process_metrics[name] = {
                    "contributors": metric.count(),
                    "minor_contributors": metric.count_minor(),
                }
        except Exception as exc:  # the report must preserve a partial metric
            metric_errors[name] = f"{type(exc).__name__}: {exc}"

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "tool": "PyDriller",
        "repo": str(repo_path),
        "commit_count_including_ref_duplicates": all_commit_count,
        "unique_commit_count": len(unique),
        "author_count": len(authors),
        "authors": dict(authors),
        "merge_commits": sum(1 for commit in unique if commit["merge"]),
        "empty_commits_by_modified_files": sum(
            1 for commit in unique if commit["empty_by_modified_files"]
        ),
        "total_insertions": sum(commit["insertions"] for commit in unique),
        "total_deletions": sum(commit["deletions"] for commit in unique),
        "total_churn": sum(commit["lines"] for commit in unique),
        "total_modified_files": len(all_modified),
        "change_types": dict(Counter(item["change_type"] for item in all_modified)),
        "first_author_timestamp": iso(min((c["author_date"] for c in unique), default=None)),
        "last_author_timestamp": iso(max((c["author_date"] for c in unique), default=None)),
        "first_committer_timestamp": iso(min((c["committer_date"] for c in unique), default=None)),
        "last_committer_timestamp": iso(max((c["committer_date"] for c in unique), default=None)),
        "process_metrics": process_metrics,
        "process_metric_errors": metric_errors,
        "sample_commits": sample_commits,
        "runtime_ms": elapsed_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run(args.repo.resolve())
    except Exception as exc:
        error = {"tool": "PyDriller", "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(error, indent=2, default=str))
        return 1
    rendered = json.dumps(report, indent=2, default=str)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
