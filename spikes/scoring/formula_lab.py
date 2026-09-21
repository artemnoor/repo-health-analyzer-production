"""Deterministic, non-production lab for the six-category Repo Health Score."""

from __future__ import annotations

import argparse
import json
import math
from itertools import product
from typing import Any

CATEGORIES = ("documentation", "activity", "issues", "cicd", "security", "code_health")
WEIGHTS = {"documentation": 0.15, "activity": 0.15, "issues": 0.15, "cicd": 0.15, "security": 0.20, "code_health": 0.20}
ESSENTIAL = ("security", "code_health")
MEASURED = "MEASURED"
EXCLUDED = {"NOT_APPLICABLE", "UNAVAILABLE", "ERROR"}


def category(score: float | None, status: str = MEASURED, coverage: float = 1.0, confidence: float = 1.0) -> dict[str, Any]:
    return {"score": score, "status": status, "coverage": coverage, "confidence": confidence}


def base_case() -> dict[str, dict[str, Any]]:
    return {name: category(85.0) for name in CATEGORIES}


def scenarios() -> dict[str, dict[str, dict[str, Any]]]:
    cases: dict[str, dict[str, dict[str, Any]]] = {"healthy_reference": base_case()}
    cases["critical_vulnerability_or_secret"] = base_case()
    cases["critical_vulnerability_or_secret"]["security"] = category(0.0)
    cases["critical_vulnerability_or_secret"]["security"]["critical_finding"] = True
    cases["security_api_unavailable"] = base_case()
    cases["security_api_unavailable"]["security"] = category(None, "UNAVAILABLE", 0.0, 0.0)
    cases["one_hundred_empty_commits"] = base_case()
    cases["one_hundred_empty_commits"]["activity"] = category(45.0)
    cases["one_issue_insufficient_sample"] = base_case()
    cases["one_issue_insufficient_sample"]["issues"] = category(35.0, MEASURED, 0.20, 0.20)
    cases["ci_failure_rate_thirty_percent"] = base_case()
    cases["ci_failure_rate_thirty_percent"]["cicd"] = category(65.0)
    cases["ci_not_configured"] = base_case()
    cases["ci_not_configured"]["cicd"] = category(0.0)
    cases["documentation_improves"] = base_case()
    cases["documentation_improves"]["documentation"] = category(98.0)
    cases["complexity_worsens"] = base_case()
    cases["complexity_worsens"]["code_health"] = category(35.0)
    cases["code_health_engine_unavailable"] = base_case()
    cases["code_health_engine_unavailable"]["code_health"] = category(None, "UNAVAILABLE", 0.0, 0.0)
    cases["small_new_repository"] = {
        "documentation": category(80.0, MEASURED, 0.80, 0.80),
        "activity": category(None, "NO_ACTIVITY", 0.80, 0.80),
        "issues": category(None, "NO_ACTIVITY", 0.80, 0.80),
        "cicd": category(None, "NOT_APPLICABLE", 0.0, 0.0),
        "security": category(95.0, MEASURED, 0.80, 0.80),
        "code_health": category(90.0, MEASURED, 0.80, 0.80),
    }
    cases["mature_large_repository"] = {
        "documentation": category(92.0), "activity": category(88.0), "issues": category(86.0),
        "cicd": category(90.0), "security": category(94.0), "code_health": category(87.0),
    }
    return cases


def q_value(item: dict[str, Any]) -> float:
    if item["status"] in EXCLUDED:
        return 0.0
    return max(0.0, min(1.0, float(item["coverage"]))) * max(0.0, min(1.0, float(item["confidence"])))


def coverage_k(data: dict[str, dict[str, Any]], weights: dict[str, float] = WEIGHTS) -> float:
    return sum(weights[name] * q_value(data[name]) for name in CATEGORIES) / sum(weights.values())


def eligible(data: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name in CATEGORIES if data[name]["status"] == MEASURED and data[name]["score"] is not None]


def arithmetic(data: dict[str, dict[str, Any]], weights: dict[str, float] = WEIGHTS) -> float | None:
    names = eligible(data)
    denominator = sum(weights[name] for name in names)
    if not denominator:
        return None
    return sum(weights[name] * float(data[name]["score"]) for name in names) / denominator


def geometric(data: dict[str, dict[str, Any]], weights: dict[str, float] = WEIGHTS, epsilon: float = 1e-6) -> float | None:
    names = eligible(data)
    denominator = sum(weights[name] for name in names)
    if not denominator:
        return None
    return math.exp(sum(weights[name] * math.log(max(float(data[name]["score"]), epsilon)) for name in names) / denominator)


def hybrid(data: dict[str, dict[str, Any]], security_cap: float = 40.0) -> float | None:
    value = arithmetic(data)
    if value is None:
        return None
    if data["security"].get("critical_finding") and data["security"]["status"] == MEASURED:
        value = min(value, security_cap)
    return value


def presentation(data: dict[str, dict[str, Any]], score: float | None, *, full_k: float = 0.75, provisional_k: float = 0.50) -> str:
    k = coverage_k(data)
    names = eligible(data)
    essential_q = min(q_value(data[name]) for name in ESSENTIAL)
    unavailable = any(data[name]["status"] in {"UNAVAILABLE", "ERROR"} for name in CATEGORIES)
    low_quality = any(data[name]["status"] == MEASURED and 0 < q_value(data[name]) < provisional_k for name in CATEGORIES)
    if score is None or k < provisional_k or len(names) < 3:
        return "INSUFFICIENT_DATA"
    if k < full_k or essential_q < full_k or len(names) < 4 or unavailable or low_quality:
        return "PROVISIONAL_SCORE"
    return "SCORE"


def evaluate(data: dict[str, dict[str, Any]], security_cap: float = 40.0, *, full_k: float = 0.75, provisional_k: float = 0.50) -> dict[str, Any]:
    result = {"arithmetic": arithmetic(data), "geometric": geometric(data), "hybrid": hybrid(data, security_cap), "coverage_k": coverage_k(data), "eligible_categories": eligible(data)}
    result["presentation"] = presentation(data, result["hybrid"], full_k=full_k, provisional_k=provisional_k)
    return result


def sensitivity() -> dict[str, Any]:
    base = scenarios()["mature_large_repository"]
    weight_rows = []
    for security_weight, code_weight in product((0.18, 0.20, 0.22), repeat=2):
        remaining = (1.0 - security_weight - code_weight) / 4.0
        weights = {name: remaining for name in ("documentation", "activity", "issues", "cicd")}
        weights.update({"security": security_weight, "code_health": code_weight})
        weight_rows.append({"security_weight": security_weight, "code_health_weight": code_weight, "healthy_arithmetic": arithmetic(base, weights)})
    small = scenarios()["small_new_repository"]
    threshold_rows = [{"provisional_k": p, "full_k": f, "presentation": presentation(small, hybrid(small), full_k=f, provisional_k=p)} for p, f in ((0.40, 0.70), (0.50, 0.75), (0.60, 0.80))]
    critical = scenarios()["critical_vulnerability_or_secret"]
    cap_rows = [{"security_cap": cap, "hybrid": hybrid(critical, cap)} for cap in (30.0, 40.0, 50.0)]
    return {"weights": weight_rows, "presentation_thresholds": threshold_rows, "security_caps": cap_rows}


def invariants() -> dict[str, bool]:
    cases = scenarios()
    healthy = evaluate(cases["healthy_reference"])
    return {
        "documentation_monotone": evaluate(cases["documentation_improves"])["hybrid"] >= healthy["hybrid"],
        "complexity_monotone": evaluate(cases["complexity_worsens"])["hybrid"] < healthy["hybrid"],
        "unavailable_security_not_zero": evaluate(cases["security_api_unavailable"])["hybrid"] > 0,
        "no_ci_is_measured_negative": evaluate(cases["ci_not_configured"])["hybrid"] < healthy["hybrid"],
        "critical_security_cap_applies": evaluate(cases["critical_vulnerability_or_secret"])["hybrid"] <= 40.0,
        "one_issue_is_not_full_score": evaluate(cases["one_issue_insufficient_sample"])["presentation"] != "SCORE",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    cases = scenarios()
    result = {"weights": WEIGHTS, "scenarios": {name: evaluate(data) for name, data in cases.items()}, "sensitivity": sensitivity(), "invariants": invariants()}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    print("Scenario | arithmetic | geometric | hybrid | K | presentation")
    print("--- | ---: | ---: | ---: | ---: | ---")
    for name, row in result["scenarios"].items():
        print(f"{name} | {row['arithmetic']:.2f} | {row['geometric']:.2f} | {row['hybrid']:.2f} | {row['coverage_k']:.2f} | {row['presentation']}")
    print("\nInvariants:")
    for name, value in result["invariants"].items():
        print(f"- {name}: {value}")
    print("\nSensitivity:")
    print(json.dumps(result["sensitivity"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
