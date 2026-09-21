"""Code Health calibration-v2 policy over SonarQube/Git/TODO facts."""

from collections.abc import Mapping

from ...contracts.results import CategoryStatus, Confidence, Finding, HealthCategory, Limitation
from ..base import Analyzer, AnalyzerEvaluation
from .policy import POLICY_DIGEST


class CodeHealthAnalyzer(Analyzer):
    id = "repo-health.code-health"
    version = "repo-health-code-health-v1"
    category = HealthCategory.CODE_HEALTH
    fact_group = "code_health"
    policy_digest = POLICY_DIGEST
    negative_keys = ("bug_count", "code_smell_count", "todo_count", "fixme_count")

    @staticmethod
    def _inverse(value: float | None, good: float, bad: float) -> float | None:
        if value is None:
            return None
        return max(0.0, min(100.0, 100.0 - (max(0.0, value) - good) / max(bad - good, 1.0) * 100.0))

    @staticmethod
    def _rating(value: object) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
            return max(0.0, min(100.0, numeric))
        except (TypeError, ValueError):
            return {"a": 100.0, "b": 85.0, "c": 70.0, "d": 45.0, "e": 15.0}.get(str(value).strip().casefold())

    def evaluate(self, analyzer_input, observations: Mapping[str, object], evidence_id: str) -> AnalyzerEvaluation:
        if not observations:
            return AnalyzerEvaluation(score=None)

        def number(name: str, default: float | None = None) -> float | None:
            value = observations.get(name, default)
            try:
                return None if value is None else float(value)
            except (TypeError, ValueError):
                return default

        ncloc = number("ncloc", number("lines_of_code", 0.0)) or 0.0
        rating = self._rating(observations.get("maintainability_rating", observations.get("sqale_rating")))
        debt = number("technical_debt_minutes", number("sqale_index"))
        smells = number("code_smells")
        debt_score = self._inverse(debt / (ncloc / 1000.0) if debt is not None and ncloc else debt, 0.0, 300.0)
        smell_score = self._inverse(smells / (ncloc / 1000.0) if smells is not None and ncloc else smells, 0.0, 50.0)
        maintainability_values = [value for value in (rating, debt_score, smell_score) if value is not None]
        maintainability = sum(maintainability_values) / len(maintainability_values) if maintainability_values else None

        cognitive = number("cognitive_complexity")
        cyclomatic = number("cyclomatic_complexity", number("complexity"))
        complexity_values = [
            self._inverse(cognitive / (ncloc / 1000.0) if cognitive is not None and ncloc else cognitive, 0.0, 50.0),
            self._inverse(
                cyclomatic / (ncloc / 1000.0) if cyclomatic is not None and ncloc else cyclomatic, 0.0, 100.0
            ),
        ]
        complexity_values = [value for value in complexity_values if value is not None]
        complexity = sum(complexity_values) / len(complexity_values) if complexity_values else None
        duplication = number("duplicated_lines_density")
        if duplication is None:
            duplicated_lines = number("duplicated_lines")
            duplication = duplicated_lines / ncloc * 100.0 if duplicated_lines is not None and ncloc else None
        duplication_score = self._inverse(duplication, 0.0, 20.0)
        todo_density = number("todo_density_per_kloc")
        old_ratio = number("todo_old_ratio")
        todo_values = [
            value
            for value in (
                self._inverse(todo_density, 0.0, 50.0),
                100.0 - min(100.0, (old_ratio or 0.0) * 100.0) if old_ratio is not None else None,
            )
            if value is not None
        ]
        todo_score = sum(todo_values) / len(todo_values) if todo_values else None
        hotspot_count = number("hotspot_count")
        source_files = number("source_files")
        hotspot_score = (
            max(0.0, 100.0 - min(100.0, hotspot_count / max(1.0, source_files or 1.0) * 100.0))
            if hotspot_count is not None
            else None
        )
        blob = number("max_blob_size")
        path_depth = number("max_path_depth")
        git_values = [
            value
            for value in (self._inverse(blob, 0.0, 1_000_000.0), self._inverse(path_depth, 0.0, 20.0))
            if value is not None
        ]
        git_score = sum(git_values) / len(git_values) if git_values else None
        components = {
            "maintainability_debt": maintainability,
            "complexity": complexity,
            "duplication": duplication_score,
            "hotspots_churn": hotspot_score,
            "todo_debt": todo_score,
            "git_structure": git_score,
        }
        weights = {
            "maintainability_debt": 0.35,
            "complexity": 0.15,
            "duplication": 0.15,
            "hotspots_churn": 0.15,
            "todo_debt": 0.10,
            "git_structure": 0.10,
        }
        eligible = {name: value for name, value in components.items() if value is not None}
        if eligible:
            total_weight = sum(weights[name] for name in eligible)
            score = sum(float(value) * weights[name] for name, value in eligible.items()) / total_weight
        else:
            explicit = number("code_health_score", number("score"))
            score = max(0.0, min(100.0, explicit)) if explicit is not None else None
        confidence = number("confidence", 1.0 if eligible else 0.0) or 0.0
        partial = (
            observations.get("partial") is True
            or observations.get("collection_state") == "partial"
            or bool(analyzer_input.facts.code_health.limitations)
        )
        if partial and score is not None:
            score = min(score, 80.0)
        findings: list[Finding] = []
        for dimension, count, severity in (
            ("bugs", int(max(0.0, number("bug_count", number("reliability_bugs", 0.0)) or 0.0)), "high"),
            ("code_smells", int(max(0.0, number("code_smell_count", number("code_smells", 0.0)) or 0.0)), "medium"),
            ("todo_debt", int(max(0.0, number("todo_count", 0.0) or 0.0)), "low"),
        ):
            if count:
                findings.append(
                    Finding(
                        analyzer_id=self.id,
                        category=self.category,
                        dimension=dimension,
                        severity=severity,
                        confidence=Confidence(
                            value=max(0.0, min(1.0, confidence)), level="high" if confidence >= 0.9 else "medium"
                        ),
                        reason=f"Code Health facts report {count} {dimension.replace('_', ' ')}",
                        evidence_ids=(evidence_id,),
                    )
                )
        limitations = (
            (
                Limitation(
                    code="code_health.partial",
                    reason="One or more Code Health engines returned partial facts",
                    affected_scope="code_health",
                ),
            )
            if partial
            else ()
        )
        status = (
            CategoryStatus.INCONCLUSIVE
            if score is None
            else CategoryStatus.FAIL
            if score < 40
            else CategoryStatus.WARN
            if partial or findings or score < 75
            else CategoryStatus.PASS
        )
        return AnalyzerEvaluation(
            score=score,
            status=status,
            metrics={
                "code_health_score": score,
                **{name: value for name, value in components.items() if value is not None},
            },
            findings=tuple(findings),
            limitations=limitations,
            coverage=observations.get("coverage"),
            confidence=confidence,
        )


__all__ = ["CodeHealthAnalyzer"]
