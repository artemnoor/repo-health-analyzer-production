"""Composition boundary for Code Health source adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import structlog

from ....analysis.analyzer_integration.ports import ProcessExecutor
from .code_health_facts import (
    CodeHealthFacts,
    CodeHealthPolicy,
    CodeHealthStatus,
    aggregate_status,
    load_code_health_policy,
    stable_digest,
)
from .contracts import AnalyzerContext, AnalyzerResult
from .git_sizer_adapter import GitSizerAdapter
from .process import workspace_root
from .sonarqube_adapter import SonarQubeAdapter, SonarQubeTransport
from .todo_debt_adapter import TodoDebtAdapter

log = structlog.get_logger("health.code_health.collector")

CODE_HEALTH_COLLECTOR_VERSION = "code-health-collector-v1"


@dataclass(frozen=True)
class CodeHealthSourcePorts:
    """Optional injected snapshots/transports used by the collector."""

    sonarqube_snapshot: Mapping[str, Any] | str | None = None
    sonarqube_transport: SonarQubeTransport | None = None
    git_sizer_snapshot: Mapping[str, Any] | str | None = None
    git_sizer_process: ProcessExecutor | None = None
    todo_snapshot: Mapping[str, Any] | None = None


def _status_for_error(exc: BaseException) -> CodeHealthStatus:
    del exc
    return CodeHealthStatus.ERROR


class CodeHealthFactsCollector:
    """Collect bounded, normalized Code Health facts without scoring them."""

    def __init__(self) -> None:
        self.sonarqube = SonarQubeAdapter()
        self.git_sizer = GitSizerAdapter()
        self.todo = TodoDebtAdapter()

    def collect(
        self,
        context: AnalyzerContext,
        baseline: AnalyzerResult | None = None,
        *,
        source_ports: CodeHealthSourcePorts | None = None,
        policy: CodeHealthPolicy | None = None,
    ) -> CodeHealthFacts:
        ports = source_ports or CodeHealthSourcePorts()
        resolved_policy = policy or self._policy(context)
        inventory = context.inventory
        sonar_snapshot = ports.sonarqube_snapshot
        if sonar_snapshot is None:
            raw = inventory.get("sonarqube_code_health")
            if isinstance(raw, Mapping) and isinstance(raw.get("snapshot"), (Mapping, str)):
                sonar_snapshot = raw.get("snapshot")
            elif isinstance(raw, (Mapping, str)):
                sonar_snapshot = raw
        git_snapshot = ports.git_sizer_snapshot
        if git_snapshot is None:
            raw_git = inventory.get("git_sizer")
            if isinstance(raw_git, Mapping) and isinstance(raw_git.get("snapshot"), (Mapping, str)):
                git_snapshot = raw_git.get("snapshot")
            elif isinstance(raw_git, (Mapping, str)):
                git_snapshot = raw_git
        todo_snapshot = ports.todo_snapshot or (
            inventory.get("git_history_code_health") if isinstance(inventory.get("git_history_code_health"), Mapping) else None
        )

        sonar = self._collect_sonar(context, resolved_policy, sonar_snapshot, ports.sonarqube_transport)
        git_structure = self._collect_git(context, resolved_policy, git_snapshot, ports.git_sizer_process)
        todo = self._collect_todo(context, resolved_policy, todo_snapshot)
        statuses = [sonar.status, git_structure.status, todo.status]
        engine_coverage = {
            "sonarqube": sonar.coverage,
            "git_sizer": git_structure.coverage,
            "git_history": todo.coverage,
        }
        usable = [status for status in statuses if status not in {CodeHealthStatus.NOT_APPLICABLE, CodeHealthStatus.UNAVAILABLE}]
        coverage = sum(engine_coverage.values()) / len(engine_coverage) if engine_coverage else 0.0
        confidence_values = [
            confidence
            for confidence, status in zip(
                (sonar.confidence, git_structure.confidence, todo.confidence), statuses, strict=True
            )
            if status not in {CodeHealthStatus.NOT_APPLICABLE, CodeHealthStatus.UNAVAILABLE}
        ]
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        limitations: list[str] = []
        for name, status in zip(("sonarqube", "git_sizer", "git_history"), statuses, strict=True):
            if status is CodeHealthStatus.UNAVAILABLE:
                limitations.append(f"{name} unavailable")
            elif status is CodeHealthStatus.ERROR:
                limitations.append(f"{name} returned an error")
            elif status is CodeHealthStatus.PARTIAL:
                limitations.append(f"{name} produced partial facts")
        overall = aggregate_status(statuses)
        digest = stable_digest(
            {
                "sonarqube": sonar.source_snapshot_digest,
                "git_sizer": git_structure.source_snapshot_digest,
                "todo": {
                    "status": todo.status.value,
                    "loc": todo.included_loc,
                    "todo": todo.todo_count,
                    "fixme": todo.fixme_count,
                    "old": todo.old_count,
                },
            }
        )
        diagnostics = {
            "collector_version": CODE_HEALTH_COLLECTOR_VERSION,
            "baseline_score": baseline.score if baseline else None,
            "baseline_status": baseline.status.value if baseline else None,
            "usable_engine_count": len(usable),
            "engine_count": 3,
            "policy_root": str(resolved_policy.root),
            "policy_digest": resolved_policy.digest,
        }
        log.info(
            "code_health_facts_collected",
            repo_id=context.repo_id,
            status=overall.value,
            engine_statuses={"sonarqube": sonar.status.value, "git_sizer": git_structure.status.value, "git_history": todo.status.value},
            coverage=coverage,
            confidence=confidence,
        )
        return CodeHealthFacts(
            status=overall,
            as_of_at=context.as_of_ts.astimezone(UTC),
            policy_revision=resolved_policy.revision,
            policy_digest=resolved_policy.digest,
            source_snapshot_digest=digest,
            sonar=sonar,
            git_structure=git_structure,
            todo_debt=todo,
            baseline={
                "status": baseline.status.value if baseline else None,
                "score": baseline.score if baseline else None,
                "metric_count": len(baseline.metrics) if baseline else 0,
                "finding_count": len(baseline.findings) if baseline else 0,
            },
            exclusions={
                "patterns": resolved_policy.exclusions,
                "policy_revision": resolved_policy.revision,
            },
            engine_statuses={"sonarqube": sonar.status.value, "git_sizer": git_structure.status.value, "git_history": todo.status.value},
            engine_coverage=engine_coverage,
            coverage=coverage,
            confidence=confidence,
            limitations=tuple(limitations),
            diagnostics=diagnostics,
        )

    @staticmethod
    def _policy(context: AnalyzerContext) -> CodeHealthPolicy:
        raw = context.inventory.get("code_health_policy")
        root = workspace_root()
        if isinstance(raw, Mapping):
            return CodeHealthPolicy.from_mapping(root, raw)
        return load_code_health_policy(root)

    def _collect_sonar(self, context: AnalyzerContext, policy: CodeHealthPolicy, snapshot: Mapping[str, Any] | str | None, transport: SonarQubeTransport | None):
        try:
            return self.sonarqube.collect(context, policy, snapshot=snapshot, transport=transport)
        except Exception as exc:  # adapter boundary must preserve other engines
            log.error("sonarqube_collection_failed", repo_id=context.repo_id, error_type=type(exc).__name__)
            from .code_health_facts import SonarFacts

            return SonarFacts(status=_status_for_error(exc), diagnostics={"failure_kind": "adapter_exception", "error_type": type(exc).__name__})

    def _collect_git(self, context: AnalyzerContext, policy: CodeHealthPolicy, snapshot: Mapping[str, Any] | str | None, process: ProcessExecutor | None):
        try:
            return self.git_sizer.collect(context, policy, snapshot=snapshot, runner=process)
        except Exception as exc:
            log.error("git_sizer_collection_failed", repo_id=context.repo_id, error_type=type(exc).__name__)
            from .code_health_facts import GitStructureFacts

            return GitStructureFacts(status=_status_for_error(exc), diagnostics={"failure_kind": "adapter_exception", "error_type": type(exc).__name__})

    def _collect_todo(self, context: AnalyzerContext, policy: CodeHealthPolicy, snapshot: Mapping[str, Any] | None):
        try:
            return self.todo.collect(context, policy, snapshot=snapshot)
        except Exception as exc:
            log.error("todo_collection_failed", repo_id=context.repo_id, error_type=type(exc).__name__)
            from .code_health_facts import TodoDebtFacts

            return TodoDebtFacts(status=_status_for_error(exc), diagnostics={"failure_kind": "adapter_exception", "error_type": type(exc).__name__})


__all__ = ["CODE_HEALTH_COLLECTOR_VERSION", "CodeHealthFactsCollector", "CodeHealthSourcePorts"]
