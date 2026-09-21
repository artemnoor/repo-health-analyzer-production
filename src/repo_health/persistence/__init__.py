"""Minimal target persistence."""

from .legacy import LegacyReplayError, replay_legacy_score
from .models import AnalysisRecord, AnalysisSummaryProjection, AnalyzerTaskRecord, RepositoryRecord
from .ports import PersistencePort
from .sqlite import (
    IdempotencyConflict,
    ImmutableResultConflict,
    LeaseOwnershipError,
    PersistenceDecodeError,
    SQLitePersistence,
)

__all__ = [
    "AnalysisRecord",
    "AnalysisSummaryProjection",
    "AnalyzerTaskRecord",
    "IdempotencyConflict",
    "ImmutableResultConflict",
    "LeaseOwnershipError",
    "LegacyReplayError",
    "PersistenceDecodeError",
    "PersistencePort",
    "RepositoryRecord",
    "SQLitePersistence",
    "replay_legacy_score",
]
