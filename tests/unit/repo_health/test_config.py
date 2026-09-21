"""Typed runtime configuration and capability detection gates."""

from __future__ import annotations

from repo_health.config import CapabilityState, RuntimeConfig


def test_runtime_config_reads_only_typed_non_secret_settings() -> None:
    config = RuntimeConfig.from_environment(
        {
            "REPO_HEALTH_DB": "tmp.sqlite3",
            "REPO_HEALTH_CHECKOUT_ROOT": "checkouts",
            "REPO_HEALTH_WORKER_ID": "worker-test",
            "SOURCECRAFT_URL": "https://sourcecraft.example",
            "SOURCECRAFT_TOKEN": "secret-a",
            "VALE_PATH": "vale-custom",
            "GIT_SIZER_PATH": "git-sizer-custom",
            "SONAR_URL": "https://sonar.example",
            "SONAR_TOKEN": "secret-b",
        }
    )

    assert config.db_path == "tmp.sqlite3"
    assert config.sourcecraft_token_present is True
    assert config.sonar_token_present is True
    assert "secret-a" not in config.model_dump_json()
    assert "secret-b" not in config.model_dump_json()
    assert config.digest() == RuntimeConfig.model_validate(config.model_dump()).digest()


def test_token_rotation_does_not_change_configuration_digest() -> None:
    first = RuntimeConfig.from_environment({"SOURCECRAFT_URL": "https://sourcecraft.example", "SOURCECRAFT_TOKEN": "a"})
    second = RuntimeConfig.from_environment({"SOURCECRAFT_URL": "https://sourcecraft.example", "SOURCECRAFT_TOKEN": "b"})

    assert first.digest() == second.digest()


def test_capabilities_distinguish_unavailable_and_misconfigured() -> None:
    config = RuntimeConfig.from_environment(
        {
            "SOURCECRAFT_URL": "not-a-url",
            "SONAR_URL": "https://sonar.example",
            "VALE_PATH": "C:/does-not-exist/vale.exe",
        }
    )

    statuses = {item.engine: item for item in config.capability_report()}
    assert statuses["sourcecraft"].state is CapabilityState.MISCONFIGURED
    assert statuses["sonarqube"].state is CapabilityState.MISCONFIGURED
    assert statuses["vale"].state is CapabilityState.UNAVAILABLE
    assert statuses["git.todo-history"].state is CapabilityState.AVAILABLE
    assert all("not-a-url" not in item.model_dump_json() for item in statuses.values())
