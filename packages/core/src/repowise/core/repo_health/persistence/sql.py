"""SQL adapter for immutable, serialized Repo Health envelopes."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...persistence.models import RepoHealthAnalysisEnvelope
from ..contracts.requests import canonical_json
from ..contracts.results import AnalysisEnvelope
from .ports import AnalysisEnvelopeConflictError


class SqlAnalysisEnvelopeStore:
    """Persist contract JSON while keeping ORM details behind this adapter."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def write(
        self, envelope: AnalysisEnvelope, *, snapshot_id: str | None = None
    ) -> AnalysisEnvelope:
        existing = await self.get(envelope.analysis_id)
        if existing is None:
            existing = await self.get_by_idempotency(
                envelope.request.repository.repository_id, envelope.idempotency_key
            )
        if existing is not None:
            if canonical_json(existing) != canonical_json(envelope):
                raise AnalysisEnvelopeConflictError(
                    "analysis_id or idempotency_key already belongs to different content"
                )
            return existing

        payload = envelope.model_dump(mode="json")
        row = RepoHealthAnalysisEnvelope(
            analysis_id=envelope.analysis_id,
            repository_id=envelope.request.repository.repository_id,
            idempotency_key=envelope.idempotency_key,
            facts_digest=envelope.facts_digest,
            policy_digest=envelope.policy_digest,
            schema_version=envelope.schema_version,
            request_json=canonical_json(envelope.request),
            facts_json=(canonical_json(envelope.facts) if envelope.facts is not None else None),
            category_results_json=canonical_json({"items": payload["category_results"]}),
            score_json=canonical_json(envelope.score) if envelope.score is not None else None,
            status_json=canonical_json(envelope.status),
            tool_versions_json=canonical_json(envelope.tool_versions),
            envelope_json=canonical_json(envelope),
            snapshot_id=snapshot_id,
            created_at=envelope.created_at,
            started_at=envelope.started_at,
            finished_at=envelope.finished_at,
        )
        self._session.add(row)
        await self._session.flush()
        return envelope

    async def get(self, analysis_id: str) -> AnalysisEnvelope | None:
        row = await self._session.get(RepoHealthAnalysisEnvelope, analysis_id)
        return self._decode(row)

    async def get_by_idempotency(
        self, repository_id: str, idempotency_key: str
    ) -> AnalysisEnvelope | None:
        result = await self._session.execute(
            select(RepoHealthAnalysisEnvelope).where(
                RepoHealthAnalysisEnvelope.repository_id == repository_id,
                RepoHealthAnalysisEnvelope.idempotency_key == idempotency_key,
            )
        )
        return self._decode(result.scalar_one_or_none())

    @staticmethod
    def _decode(row: RepoHealthAnalysisEnvelope | None) -> AnalysisEnvelope | None:
        if row is None:
            return None
        return AnalysisEnvelope.model_validate_json(row.envelope_json)


__all__ = ["SqlAnalysisEnvelopeStore"]
