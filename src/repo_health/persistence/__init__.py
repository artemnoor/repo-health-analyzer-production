"""Minimal target persistence."""

from .legacy import LegacyReplayError, replay_legacy_score
from .models import AnalysisRecord, AnalysisSummaryProjection, AnalyzerTaskRecord, RepositoryRecord
from .ports import PersistencePort
from .sqlite import IdempotencyConflict, ImmutableResultConflict, PersistenceDecodeError, SQLitePersistence

__all__ = [
    "AnalysisRecord",
    "AnalysisSummaryProjection",
    "AnalyzerTaskRecord",
    "IdempotencyConflict",
    "ImmutableResultConflict",
    "LegacyReplayError",
    "PersistenceDecodeError",
    "PersistencePort",
    "RepositoryRecord",
    "SQLitePersistence",
    "replay_legacy_score",
]
