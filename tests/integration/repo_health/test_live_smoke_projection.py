"""Safe offline/live-smoke projection tests."""

from __future__ import annotations

import json

from scripts.verify_production_composition import main


def test_offline_smoke_reports_six_safe_category_rows(capsys, monkeypatch) -> None:
    for name in ("SOURCECRAFT_URL", "SOURCECRAFT_TOKEN", "SONAR_URL", "SONAR_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VALE_PATH", "missing-vale")
    monkeypatch.setenv("GIT_SIZER_PATH", "missing-git-sizer")

    assert main([]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "offline"
    assert len(payload["categories"]) == 6
    assert {row["category"] for row in payload["categories"]} == {
        "documentation",
        "activity",
        "issues",
        "cicd",
        "security",
        "code-health",
    }
    assert "missing-vale" not in json.dumps(payload)
    assert "token" not in json.dumps(payload).lower()


def test_offline_smoke_marks_malformed_provider_configuration(capsys, monkeypatch) -> None:
    monkeypatch.setenv("SOURCECRAFT_URL", "not-a-url")
    monkeypatch.delenv("SOURCECRAFT_TOKEN", raising=False)

    assert main([]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["capabilities"]["sourcecraft"]["state"] == "misconfigured"
