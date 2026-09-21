"""Versioned request contracts for local and worker Repo Health execution.

These models deliberately contain repository identity and execution policy,
not checkout paths, provider request bodies, credentials, or persistence
objects.  The same JSON is therefore usable by the local executor and by a
future queue/worker transport.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_SCHEMA_VERSION = "repo-health.v1"
_SUPPORTED_SCHEMA_VERSIONS = frozenset({CONTRACT_SCHEMA_VERSION})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_REPO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_REF_RE = re.compile(r"^[^\x00-\x20\x7f]{1,255}$")
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{8,128}$")
_ANALYZER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SECRET_MARKERS = ("api_key", "apikey", "bearer ", "password", "secret", "token")


class ContractValidationError(ValueError):
    """Base class for errors raised while accepting a transport contract."""


class UnsupportedContractVersion(ContractValidationError):
    """Raised when a contract major/schema version is not understood."""

    def __init__(self, value: object, *, contract: str | None = None) -> None:
        label = f" for {contract}" if contract else ""
        super().__init__(
            f"unsupported contract schema_version{label}: {value!r}; "
            f"supported versions: {sorted(_SUPPORTED_SCHEMA_VERSIONS)!r}"
        )
        self.value = value
        self.contract = contract


class _VersionedContract(BaseModel):
    """Strict base for the public Repo Health request vocabulary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_schema_version(cls, value: object) -> object:
        if isinstance(value, Mapping) and "schema_version" in value:
            version = value["schema_version"]
            if version not in _SUPPORTED_SCHEMA_VERSIONS:
                raise UnsupportedContractVersion(version, contract=cls.__name__)
        return value

    def to_json(self) -> str:
        """Return canonical JSON suitable for transport, hashing, or caching."""

        return canonical_json(self)

    def digest(self) -> str:
        """Return the SHA-256 digest of canonical serialized contract data."""

        return contract_digest(self)


def canonical_json(value: BaseModel | Mapping[str, Any]) -> str:
    """Serialize a contract deterministically without Python-only values."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def contract_digest(value: BaseModel | Mapping[str, Any]) -> str:
    """Hash canonical JSON with no timing or runtime-only fields included."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_uri(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("canonical_uri must be a string URI")
    raw = value.strip()
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https", "git", "ssh"}:
        raise ValueError("canonical_uri must use http, https, git, or ssh")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("canonical_uri must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("canonical_uri must not contain query or fragment data")
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("canonical_uri contains an invalid host or port") from exc
    if not hostname:
        raise ValueError("canonical_uri must contain a host")
    path = parsed.path.rstrip("/")
    if not path:
        raise ValueError("canonical_uri must identify a repository path")
    hostname = hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = (scheme, port) in {("http", 80), ("https", 443)}
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    return urlunsplit((scheme, netloc, path, "", ""))


def _normalize_repository_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("repository_id must be a string")
    normalized = value.strip()
    if not _REPO_ID_RE.fullmatch(normalized):
        raise ValueError("repository_id must be a bounded stable identifier")
    if "//" in normalized or ".." in normalized:
        raise ValueError("repository_id must not contain ambiguous path segments")
    return normalized


def _normalize_provider(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("provider must be a string")
    normalized = value.strip().lower()
    if not _PROVIDER_RE.fullmatch(normalized):
        raise ValueError("provider must be a bounded lowercase identifier")
    return normalized


def _normalize_ref(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("ref must be a string")
    normalized = value.strip()
    if not _REF_RE.fullmatch(normalized):
        raise ValueError("ref contains whitespace, control characters, or is too long")
    if (
        normalized.startswith(("/", "\\", "./", "../"))
        or re.match(r"^[A-Za-z]:[\\/]", normalized)
        or ".." in normalized
        or "@{" in normalized
        or normalized.endswith(".")
        or normalized.endswith(".lock")
    ):
        raise ValueError("ref is not a valid unambiguous source reference")
    return normalized


def _normalize_sha(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("head_sha must be a hexadecimal git object ID")
    normalized = value.strip().lower()
    if not _SHA_RE.fullmatch(normalized):
        raise ValueError("head_sha must contain 40 or 64 hexadecimal characters")
    return normalized


def _normalize_optional_identifier(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a bounded stable identifier")
    if any(marker in normalized.lower() for marker in _SECRET_MARKERS):
        raise ValueError(f"{field_name} must not contain secret-like material")
    return normalized


def _normalize_digest(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a hexadecimal digest")
    normalized = value.strip().lower()
    if not _DIGEST_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be 8-128 hexadecimal characters")
    return normalized


def _normalize_utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be an aware UTC timestamp")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be an aware UTC timestamp")
    return value.astimezone(UTC)


def _normalize_analyzer_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError("requested_analyzer_ids must be an iterable of IDs") from exc
    normalized: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            raise ValueError("requested_analyzer_ids must contain strings")
        analyzer_id = item.strip().lower()
        if not _ANALYZER_ID_RE.fullmatch(analyzer_id):
            raise ValueError(f"invalid analyzer ID: {item!r}")
        normalized.add(analyzer_id)
    return tuple(sorted(normalized))


class RepositoryRef(_VersionedContract):
    """Provider-neutral repository identity used by every execution mode."""

    schema_version: Literal[CONTRACT_SCHEMA_VERSION] = CONTRACT_SCHEMA_VERSION
    repository_id: str = Field(min_length=1, max_length=200)
    canonical_uri: str = Field(min_length=1, max_length=2048)
    provider: str = Field(min_length=1, max_length=32)
    ref: str = Field(default="HEAD", min_length=1, max_length=255)
    head_sha: str | None = None
    snapshot_id: str | None = Field(default=None, max_length=128)

    _repository_id = field_validator("repository_id", mode="before")(_normalize_repository_id)
    _canonical_uri = field_validator("canonical_uri", mode="before")(_normalize_uri)
    _provider = field_validator("provider", mode="before")(_normalize_provider)
    _ref = field_validator("ref", mode="before")(_normalize_ref)
    _head_sha = field_validator("head_sha", mode="before")(_normalize_sha)
    _snapshot_id = field_validator("snapshot_id", mode="before")(
        lambda value: _normalize_optional_identifier(value, field_name="snapshot_id")
    )

    @model_validator(mode="after")
    def _identity_is_unambiguous(self) -> RepositoryRef:
        if self.repository_id.startswith(("/", "\\")):
            raise ValueError("repository_id must not be a local path")
        # Both are useful, but an explicit snapshot must not silently point at
        # a different object than the advertised immutable head.
        if (
            self.head_sha is not None
            and self.snapshot_id is not None
            and _SHA_RE.fullmatch(self.snapshot_id)
            and self.snapshot_id != self.head_sha
        ):
            raise ValueError("snapshot_id and head_sha identify different objects")
        return self


class AnalysisRequest(_VersionedContract):
    """Deterministic lifecycle envelope accepted by local or worker executors."""

    schema_version: Literal[CONTRACT_SCHEMA_VERSION] = CONTRACT_SCHEMA_VERSION
    analysis_id: str | None = Field(default=None, max_length=128)
    repository: RepositoryRef
    requested_analyzer_ids: tuple[str, ...] = ()
    mode: str = Field(default="full", min_length=1, max_length=32)
    as_of: datetime
    config_digest: str | None = Field(default=None, max_length=128)
    policy_digest: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    deadline_at: datetime | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=86_400)

    _analysis_id = field_validator("analysis_id", mode="before")(
        lambda value: _normalize_optional_identifier(value, field_name="analysis_id")
    )
    _requested_analyzer_ids = field_validator("requested_analyzer_ids", mode="before")(_normalize_analyzer_ids)
    _mode = field_validator("mode", mode="before")(
        lambda value: _normalize_optional_identifier(value, field_name="mode") or "full"
    )
    _config_digest = field_validator("config_digest", mode="before")(
        lambda value: _normalize_digest(value, field_name="config_digest")
    )
    _policy_digest = field_validator("policy_digest", mode="before")(
        lambda value: _normalize_digest(value, field_name="policy_digest")
    )
    _idempotency_key = field_validator("idempotency_key", mode="before")(
        lambda value: _normalize_optional_identifier(value, field_name="idempotency_key")
    )
    _as_of = field_validator("as_of", mode="after")(lambda value: _normalize_utc(value, field_name="as_of"))
    _deadline_at = field_validator("deadline_at", mode="after")(
        lambda value: None if value is None else _normalize_utc(value, field_name="deadline_at")
    )

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> AnalysisRequest:
        if self.deadline_at is not None and self.deadline_at <= self.as_of:
            raise ValueError("deadline_at must be after as_of")
        if self.analysis_id is None:
            payload = self.model_dump(mode="json", exclude={"analysis_id"})
            derived = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:32]
            object.__setattr__(self, "analysis_id", f"analysis-{derived}")
        return self


def _ensure_supported_version(payload: Mapping[str, Any], *, contract: str) -> None:
    version = payload.get("schema_version", CONTRACT_SCHEMA_VERSION)
    if version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedContractVersion(version, contract=contract)


def parse_repository_ref(payload: Mapping[str, Any]) -> RepositoryRef:
    """Validate an untrusted mapping with an explicit version error."""

    _ensure_supported_version(payload, contract=RepositoryRef.__name__)
    return RepositoryRef.model_validate(payload)


def parse_analysis_request(payload: Mapping[str, Any]) -> AnalysisRequest:
    """Validate an untrusted mapping with an explicit version error."""

    _ensure_supported_version(payload, contract=AnalysisRequest.__name__)
    return AnalysisRequest.model_validate(payload)


__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "AnalysisRequest",
    "ContractValidationError",
    "RepositoryRef",
    "UnsupportedContractVersion",
    "canonical_json",
    "contract_digest",
    "parse_analysis_request",
    "parse_repository_ref",
]
