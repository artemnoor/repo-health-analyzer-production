"""Explicit schema-version registry for Repo Health transport contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .requests import CONTRACT_SCHEMA_VERSION, UnsupportedContractVersion


@dataclass(frozen=True, slots=True)
class ContractVersionRegistry:
    """Small registry that fails closed on unknown contract versions."""

    versions: frozenset[str] = frozenset({CONTRACT_SCHEMA_VERSION})

    def ensure_supported(self, version: str) -> str:
        if version not in self.versions:
            raise UnsupportedContractVersion(version, contract="RepoHealth")
        return version

    def negotiate(self, offered: list[str] | tuple[str, ...]) -> str:
        """Choose the newest common version without accepting a major mismatch."""

        common = sorted(set(offered) & self.versions, reverse=True)
        if not common:
            raise UnsupportedContractVersion(
                offered,
                contract="RepoHealth",
            )
        return common[0]


CONTRACT_VERSIONS = ContractVersionRegistry()


__all__ = ["CONTRACT_VERSIONS", "ContractVersionRegistry"]
