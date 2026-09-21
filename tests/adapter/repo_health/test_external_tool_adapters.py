"""Recorded external-tool fixtures and process failure semantics."""

from __future__ import annotations

from pathlib import Path

from repo_health.collection.code_health.git_sizer import GitSizerCollector
from repo_health.collection.code_health.sonarqube import SonarQubeCollector
from repo_health.collection.code_health.todo_history import TodoHistoryCollector
from repo_health.collection.documentation.vale import ValeCollector
from repo_health.collection.git.pydriller import PyDrillerCollector
from repo_health.collection.ports import CollectionContext
from repo_health.contracts.requests import AnalysisRequest, RepositoryRef
from repo_health.infrastructure.git import GitCollector
from repo_health.infrastructure.process import ProcessOutput


class FakeRunner:
    def __init__(self, output: ProcessOutput) -> None:
        self.output = output

    def run(self, request) -> ProcessOutput:
        del request
        return self.output


def _repository() -> RepositoryRef:
    return RepositoryRef(
        repository_id="team/repository",
        canonical_uri="https://sourcecraft.example/team/repository",
        provider="sourcecraft",
        ref="main",
        head_sha="a" * 40,
    )


def _context(tmp_path: Path) -> CollectionContext:
    request = AnalysisRequest(repository=_repository(), as_of="2026-01-01T00:00:00Z")
    return CollectionContext(checkout_path=tmp_path, request=request)


def _output(stdout: str, *, exit_code: int | None = 0, **kwargs) -> ProcessOutput:
    return ProcessOutput("fixture", exit_code, stdout, "", 1, **kwargs)


def test_vale_fixture_maps_only_bounded_observations(tmp_path: Path) -> None:
    facts = ValeCollector(runner=FakeRunner(_output('{"findings":[{"file":"docs/a.md","severity":"error"}]}'))).collect(
        _repository(), context=_context(tmp_path)
    )
    assert facts.documentation.available is True
    assert {item.key: item.value for item in facts.documentation.observations} == {
        "error_count": 1,
        "finding_count": 1,
        "file_count": 1,
    }


def test_external_tool_failures_are_explicit(tmp_path: Path) -> None:
    timed_out = FakeRunner(_output("", exit_code=None, timed_out=True))
    vale_facts = ValeCollector(runner=timed_out).collect(_repository(), context=_context(tmp_path))
    assert vale_facts.documentation.available is False
    assert vale_facts.source_statuses[0].state.value == "timeout"

    sizer = GitSizerCollector(runner=FakeRunner(_output('{"metrics":{"uniqueCommitCount":{"value":12}}}')))
    sizer_facts = sizer.collect(_repository(), context=_context(tmp_path))
    assert sizer_facts.code_health.available is True
    assert dict((item.key, item.value) for item in sizer_facts.code_health.observations)["unique_commit_count"] == 12


def test_sonarqube_snapshot_and_todo_scan_are_normalized(tmp_path: Path) -> None:
    source = tmp_path / "main.py"
    source.write_text("# TODO: remove\n# FIXME: review\n", encoding="utf-8")
    sonar = SonarQubeCollector(
        fetch=lambda _repo: {"server_version": "10", "measures": [{"metric": "bugs", "value": "2"}]}
    )
    sonar_facts = sonar.collect(_repository(), context=_context(tmp_path))
    todo_facts = TodoHistoryCollector().collect(_repository(), context=_context(tmp_path))
    assert sonar_facts.code_health.available is True
    todo = {item.key: item.value for item in todo_facts.code_health.observations}
    assert todo["todo_count"] == 1
    assert todo["fixme_count"] == 1


def test_git_collector_uses_explicit_checkout_and_fake_process(tmp_path: Path) -> None:
    outputs = iter(
        [
            _output("a" * 40 + "\n"),
            _output("12\n"),
            _output("main\n"),
        ]
    )

    class Runner:
        def run(self, request) -> ProcessOutput:
            assert request.cwd == tmp_path.resolve()
            return next(outputs)

    facts = GitCollector(runner=Runner()).collect(_repository(), context=_context(tmp_path))
    assert facts.git.available is True
    assert {item.key: item.value for item in facts.git.observations}["commit_count"] == 12


def test_pydriller_unavailable_is_not_an_empty_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(__import__("sys").modules, "pydriller", None)
    facts = PyDrillerCollector().collect(_repository(), context=_context(tmp_path))
    assert facts.git.available is False
    assert facts.source_statuses[0].state.value == "unavailable"
