"""Typed, secret-free runtime configuration and capability detection."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field


class CapabilityState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    MISCONFIGURED = "misconfigured"


class CapabilityStatus(BaseModel):
    """Safe startup status for one local binary, package, or provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: str = Field(min_length=1, max_length=128)
    state: CapabilityState
    reason: str = Field(min_length=1, max_length=512)
    configured: bool

    def public_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class RuntimeConfig(BaseModel):
    """Production settings; credential values intentionally never enter this model."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    db_path: str = Field(default="repo-health.sqlite3", min_length=1, max_length=2048)
    checkout_root: str = Field(default=".", min_length=1, max_length=2048)
    worker_id: str = Field(default="worker-1", min_length=1, max_length=128)
    sourcecraft_url: str | None = Field(default=None, max_length=2048)
    vale_path: str = Field(default="vale", min_length=1, max_length=2048)
    vale_config_path: str | None = Field(default=None, max_length=2048)
    git_sizer_path: str = Field(default="git-sizer", min_length=1, max_length=2048)
    sonar_url: str | None = Field(default=None, max_length=2048)
    sourcecraft_token_present: bool = False
    sonar_token_present: bool = False

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> RuntimeConfig:
        values = dict(os.environ if environ is None else environ)

        def optional(name: str) -> str | None:
            value = values.get(name, "").strip()
            return value or None

        return cls(
            db_path=values.get("REPO_HEALTH_DB", "repo-health.sqlite3").strip() or "repo-health.sqlite3",
            checkout_root=values.get("REPO_HEALTH_CHECKOUT_ROOT", ".").strip() or ".",
            worker_id=values.get("REPO_HEALTH_WORKER_ID", "worker-1").strip() or "worker-1",
            sourcecraft_url=optional("SOURCECRAFT_URL"),
            vale_path=values.get("VALE_PATH", "vale").strip() or "vale",
            vale_config_path=optional("VALE_CONFIG_PATH"),
            git_sizer_path=values.get("GIT_SIZER_PATH", "git-sizer").strip() or "git-sizer",
            sonar_url=optional("SONAR_URL"),
            sourcecraft_token_present=bool(
                values.get("SOURCECRAFT_TOKEN", "").strip() or values.get("SOURCECRAFT_PAT", "").strip()
            ),
            sonar_token_present=bool(values.get("SONAR_TOKEN", "").strip()),
        )

    def digest(self) -> str:
        """Return a deterministic digest that excludes credentials and presence bits."""

        payload = {
            "db_path": self.db_path,
            "checkout_root": self.checkout_root,
            "worker_id": self.worker_id,
            "sourcecraft_url": self.sourcecraft_url,
            "vale_path": self.vale_path,
            "vale_config_path": self.vale_config_path,
            "git_sizer_path": self.git_sizer_path,
            "sonar_url": self.sonar_url,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def capability_report(self) -> tuple[CapabilityStatus, ...]:
        statuses = (
            self._binary_capability("git", "git", required=True),
            self._package_capability("pydriller", "pydriller"),
            self._binary_capability("vale", self.vale_path),
            self._binary_capability("git-sizer", self.git_sizer_path),
            self._url_capability(
                "sonarqube",
                self.sonar_url,
                self.sonar_token_present,
                url_name="SONAR_URL",
                token_name="SONAR_TOKEN",
            ),
            self._url_capability(
                "sourcecraft",
                self.sourcecraft_url,
                self.sourcecraft_token_present,
                url_name="SOURCECRAFT_URL",
                token_name="SOURCECRAFT_TOKEN or SOURCECRAFT_PAT",
            ),
            CapabilityStatus(
                engine="git.todo-history",
                state=CapabilityState.AVAILABLE,
                reason="built-in bounded checkout scan",
                configured=True,
            ),
        )
        return tuple(sorted(statuses, key=lambda item: item.engine))

    @staticmethod
    def _binary_capability(engine: str, executable: str, *, required: bool = False) -> CapabilityStatus:
        found = _find_executable(executable)
        if found:
            return CapabilityStatus(
                engine=engine,
                state=CapabilityState.AVAILABLE,
                reason="executable available",
                configured=True,
            )
        return CapabilityStatus(
            engine=engine,
            state=CapabilityState.UNAVAILABLE,
            reason="required executable is unavailable" if required else "optional executable is unavailable",
            configured=executable != engine,
        )

    @staticmethod
    def _package_capability(engine: str, package: str) -> CapabilityStatus:
        available = importlib.util.find_spec(package) is not None
        return CapabilityStatus(
            engine=engine,
            state=CapabilityState.AVAILABLE if available else CapabilityState.UNAVAILABLE,
            reason="package importable" if available else "package is unavailable",
            configured=True,
        )

    @staticmethod
    def _url_capability(
        engine: str,
        url: str | None,
        token_present: bool,
        *,
        url_name: str,
        token_name: str,
    ) -> CapabilityStatus:
        if not url:
            return CapabilityStatus(
                engine=engine,
                state=CapabilityState.UNAVAILABLE,
                reason=f"{url_name} is not configured",
                configured=False,
            )
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return CapabilityStatus(
                engine=engine,
                state=CapabilityState.MISCONFIGURED,
                reason=f"{url_name} must be an http(s) URL without credentials",
                configured=True,
            )
        if not token_present:
            return CapabilityStatus(
                engine=engine,
                state=CapabilityState.MISCONFIGURED,
                reason=f"{token_name} is not configured",
                configured=True,
            )
        return CapabilityStatus(
            engine=engine,
            state=CapabilityState.AVAILABLE,
            reason="endpoint and credential are configured",
            configured=True,
        )


def _find_executable(value: str) -> str | None:
    candidate = Path(value)
    if candidate.parent != Path(".") or candidate.is_absolute():
        return str(candidate) if candidate.is_file() else None
    return shutil.which(value)


__all__ = ["CapabilityState", "CapabilityStatus", "RuntimeConfig"]
