"""SQLite persistence used by the local/hackathon deployment.

The schema stores only serialized versioned contracts and does not initialize
unrelated product tables or storage systems.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from ..contracts.execution import AnalyzerTask, ExecutionOutcome
from ..contracts.requests import AnalysisRequest, RepositoryRef
from ..contracts.results import AnalysisEnvelope, AnalysisState, AnalysisStatus
from .models import AnalysisRecord, AnalysisSummaryProjection, AnalyzerTaskRecord, RepositoryRecord, now_utc

log = structlog.get_logger("repo_health.persistence.sqlite")


class IdempotencyConflict(RuntimeError):
    """The same key was used for a different serialized request."""


class ImmutableResultConflict(RuntimeError):
    """An already committed result cannot be overwritten."""


class PersistenceDecodeError(ValueError):
    """Stored JSON is corrupt or no longer satisfies the target contract."""


class SQLitePersistence:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS repositories (
                    repository_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analyses (
                    analysis_id TEXT PRIMARY KEY,
                    repository_id TEXT NOT NULL REFERENCES repositories(repository_id),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    envelope TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analyzer_tasks (
                    task_id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id),
                    analyzer_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    task TEXT NOT NULL,
                    outcome TEXT,
                    available_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analyzer_tasks_claim ON analyzer_tasks(status, available_at, analyzer_id);
                """
            )
            self._connection.commit()

    def register_repository(self, repository: RepositoryRef) -> RepositoryRecord:
        current = now_utc()
        payload = repository.to_json()
        with self._lock:
            row = self._connection.execute(
                "SELECT payload, created_at FROM repositories WHERE repository_id = ?", (repository.repository_id,)
            ).fetchone()
            created_at = _parse_dt(row["created_at"]) if row else current
            if row and row["payload"] != payload:
                # Repository identity is stable; a new snapshot belongs to a new analysis.
                raise IdempotencyConflict(f"repository identity changed: {repository.repository_id}")
            self._connection.execute(
                "INSERT OR REPLACE INTO repositories(repository_id,payload,created_at,updated_at) VALUES(?,?,?,?)",
                (repository.repository_id, payload, _iso(created_at), _iso(current)),
            )
            self._connection.commit()
        return RepositoryRecord(repository=repository, created_at=created_at, updated_at=current)

    def create_analysis(self, request: AnalysisRequest) -> AnalysisRecord:
        self.register_repository(request.repository)
        current = now_utc()
        key = request.idempotency_key or request.digest()
        envelope = AnalysisEnvelope(
            analysis_id=request.analysis_id,
            request=request,
            status=AnalysisStatus(analysis_id=request.analysis_id, state=AnalysisState.QUEUED),
            idempotency_key=key,
            policy_digest=request.policy_digest,
            created_at=current,
        )
        with self._lock:
            row = self._connection.execute("SELECT * FROM analyses WHERE idempotency_key = ?", (key,)).fetchone()
            if row:
                existing = self._decode_analysis(row)
                if existing.envelope.request.to_json() != request.to_json():
                    raise IdempotencyConflict(f"idempotency key already belongs to another request: {key}")
                return existing
            self._connection.execute(
                "INSERT INTO analyses(analysis_id,repository_id,idempotency_key,state,envelope,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (
                    request.analysis_id,
                    request.repository.repository_id,
                    key,
                    AnalysisState.QUEUED.value,
                    envelope.to_json(),
                    _iso(current),
                    _iso(current),
                ),
            )
            self._connection.commit()
        return AnalysisRecord(
            analysis_id=request.analysis_id,
            repository_id=request.repository.repository_id,
            idempotency_key=key,
            state=AnalysisState.QUEUED,
            envelope=envelope,
            created_at=current,
            updated_at=current,
        )

    def get_analysis(self, analysis_id: str) -> AnalysisRecord | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
        return self._decode_analysis(row) if row else None

    def get_analysis_by_idempotency(self, key: str) -> AnalysisRecord | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM analyses WHERE idempotency_key = ?", (key,)).fetchone()
        return self._decode_analysis(row) if row else None

    def get_summary(self, analysis_id: str) -> AnalysisSummaryProjection | None:
        record = self.get_analysis(analysis_id)
        if record is None:
            return None
        score = record.envelope.score
        limitations = len(record.envelope.status.failed_analyzer_ids)
        if score is not None:
            limitations += len(score.limitations)
        limitations += sum(len(item.limitations) for item in record.envelope.category_results)
        return AnalysisSummaryProjection(
            analysis_id=record.analysis_id,
            repository_id=record.repository_id,
            state=record.state,
            overall_score=score.overall_score if score is not None else None,
            score_status=score.score_status if score is not None else None,
            category_count=len(record.envelope.category_results),
            limitation_count=limitations,
            updated_at=record.updated_at,
        )

    def commit_envelope(self, envelope: AnalysisEnvelope) -> AnalysisRecord:
        current = now_utc()
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM analyses WHERE analysis_id = ?", (envelope.analysis_id,)
            ).fetchone()
            if not row:
                raise KeyError(envelope.analysis_id)
            existing = self._decode_analysis(row)
            if (
                existing.envelope.request.to_json() != envelope.request.to_json()
                or existing.envelope.idempotency_key != envelope.idempotency_key
            ):
                raise IdempotencyConflict(f"analysis identity changed: {envelope.analysis_id}")
            if existing.envelope.score is not None:
                same_result = (
                    envelope.score is not None
                    and existing.envelope.score.to_json() == envelope.score.to_json()
                    and existing.envelope.category_results == envelope.category_results
                    and existing.envelope.facts_digest == envelope.facts_digest
                )
                if not same_result:
                    raise ImmutableResultConflict(envelope.analysis_id)
                return existing
            self._connection.execute(
                "UPDATE analyses SET state=?, envelope=?, updated_at=? WHERE analysis_id=?",
                (envelope.status.state.value, envelope.to_json(), _iso(current), envelope.analysis_id),
            )
            self._connection.commit()
        return AnalysisRecord(
            analysis_id=envelope.analysis_id,
            repository_id=envelope.request.repository.repository_id,
            idempotency_key=envelope.idempotency_key,
            state=envelope.status.state,
            envelope=envelope,
            created_at=existing.created_at,
            updated_at=current,
        )

    def enqueue_task(self, task: AnalyzerTask) -> AnalyzerTaskRecord:
        current = now_utc()
        with self._lock:
            row = self._connection.execute("SELECT * FROM analyzer_tasks WHERE task_id = ?", (task.task_id,)).fetchone()
            if row:
                existing = self._decode_task(row)
                if existing.task.to_json() != task.to_json():
                    raise IdempotencyConflict(f"task identity changed: {task.task_id}")
                return existing
            self._connection.execute(
                "INSERT INTO analyzer_tasks(task_id,analysis_id,analyzer_id,status,attempt,task,available_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    task.task_id,
                    task.analysis_id,
                    task.analyzer_id,
                    "queued",
                    task.attempt,
                    task.to_json(),
                    _iso(current),
                    _iso(current),
                ),
            )
            self._connection.commit()
        return AnalyzerTaskRecord(
            task_id=task.task_id,
            analysis_id=task.analysis_id,
            analyzer_id=task.analyzer_id,
            status="queued",
            attempt=task.attempt,
            task=task,
            available_at=current,
            updated_at=current,
        )

    def claim_task(self, *, worker_id: str, now: datetime, lease_seconds: float) -> AnalyzerTaskRecord | None:
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT * FROM analyzer_tasks WHERE (status IN ('queued','retry') AND available_at <= ?) OR (status='running' AND lease_expires_at <= ?) ORDER BY available_at, analyzer_id, task_id LIMIT 1",
                (_iso(now), _iso(now)),
            ).fetchone()
            if not row:
                self._connection.commit()
                return None
            attempt = int(row["attempt"]) + (1 if row["status"] in {"retry", "running"} else 0)
            task = AnalyzerTask.model_validate(json.loads(row["task"])).model_copy(update={"attempt": attempt})
            self._connection.execute(
                "UPDATE analyzer_tasks SET status='running',attempt=?,task=?,lease_owner=?,lease_expires_at=?,updated_at=? WHERE task_id=?",
                (attempt, task.to_json(), worker_id, _iso(lease_until), _iso(now), row["task_id"]),
            )
            self._connection.commit()
            refreshed = self._connection.execute(
                "SELECT * FROM analyzer_tasks WHERE task_id=?", (row["task_id"],)
            ).fetchone()
        return self._decode_task(refreshed)

    def complete_task(self, outcome: ExecutionOutcome) -> AnalyzerTaskRecord:
        current = now_utc()
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM analyzer_tasks WHERE task_id=?", (outcome.task_id,)
            ).fetchone()
            if not row:
                raise KeyError(outcome.task_id)
            if row["status"] == "completed":
                existing = self._decode_task(row)
                if existing.outcome is not None and existing.outcome.to_json() == outcome.to_json():
                    return existing
                raise ImmutableResultConflict(outcome.task_id)
            terminal_status = "completed" if outcome.state.value == "completed" else "failed"
            self._connection.execute(
                "UPDATE analyzer_tasks SET status=?,outcome=?,lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE task_id=?",
                (terminal_status, outcome.to_json(), _iso(current), outcome.task_id),
            )
            self._connection.commit()
            refreshed = self._connection.execute(
                "SELECT * FROM analyzer_tasks WHERE task_id=?", (outcome.task_id,)
            ).fetchone()
        return self._decode_task(refreshed)

    def renew_task(self, *, task_id: str, worker_id: str, now: datetime, lease_seconds: float) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE analyzer_tasks SET lease_expires_at=?,updated_at=? WHERE task_id=? AND status='running' AND lease_owner=?",
                (_iso(lease_until), _iso(now), task_id, worker_id),
            )
            self._connection.commit()
        return cursor.rowcount == 1

    def fail_task(self, task_id: str, *, retry: bool, error: str, available_at: datetime) -> None:
        current = now_utc()
        with self._lock:
            row = self._connection.execute("SELECT status FROM analyzer_tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row["status"] == "completed":
                raise ImmutableResultConflict(task_id)
            self._connection.execute(
                "UPDATE analyzer_tasks SET status=?,available_at=?,lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE task_id=?",
                ("retry" if retry else "failed", _iso(available_at), _iso(current), task_id),
            )
            self._connection.commit()
        log.warning("analyzer_task_failed", task_id=task_id, retry=retry, error_kind=error[:128])

    def _decode_analysis(self, row: sqlite3.Row) -> AnalysisRecord:
        try:
            envelope = AnalysisEnvelope.model_validate(json.loads(row["envelope"]))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise PersistenceDecodeError(f"invalid analysis envelope: {row['analysis_id']}") from exc
        return AnalysisRecord(
            analysis_id=row["analysis_id"],
            repository_id=row["repository_id"],
            idempotency_key=row["idempotency_key"],
            state=AnalysisState(row["state"]),
            envelope=envelope,
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )

    def _decode_task(self, row: sqlite3.Row) -> AnalyzerTaskRecord:
        try:
            outcome = ExecutionOutcome.model_validate(json.loads(row["outcome"])) if row["outcome"] else None
            task = AnalyzerTask.model_validate(json.loads(row["task"]))
            return AnalyzerTaskRecord(
                task_id=row["task_id"],
                analysis_id=row["analysis_id"],
                analyzer_id=row["analyzer_id"],
                status=row["status"],
                attempt=int(row["attempt"]),
                lease_owner=row["lease_owner"],
                lease_expires_at=_parse_dt(row["lease_expires_at"]) if row["lease_expires_at"] else None,
                task=task,
                outcome=outcome,
                available_at=_parse_dt(row["available_at"]),
                updated_at=_parse_dt(row["updated_at"]),
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise PersistenceDecodeError(f"invalid analyzer task: {row['task_id']}") from exc


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


__all__ = ["IdempotencyConflict", "ImmutableResultConflict", "PersistenceDecodeError", "SQLitePersistence"]
