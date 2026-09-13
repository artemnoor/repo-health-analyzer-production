"""The native tool matrix is explicit about required vs optional runtimes."""

from pathlib import Path

import yaml


def test_native_tools_have_modes_timeouts_and_failure_policy() -> None:
    root = Path(__file__).parents[2]
    config = yaml.safe_load((root / "config" / "analyzers" / "native-tools.yaml").read_text())
    policy = config["policy"]
    assert policy["max_concurrent_processes"] >= 1
    assert policy["max_files"] > 0
    assert policy["max_commits"] > 0
    assert policy["failure_policy"]["skipped"] == "visible_skip"
    for tool_id, tool in config["tools"].items():
        assert tool["command"], tool_id
        assert tool["timeout"] > 0, tool_id
        assert tool["enabled_by_mode"], tool_id
