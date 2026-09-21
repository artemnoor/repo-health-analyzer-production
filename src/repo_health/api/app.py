"""Narrow backend-only REST surface for Repository Health Analyzer."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import RuntimeConfig
from ..contracts.requests import AnalysisRequest, RepositoryRef
from ..infrastructure.scheduler import IntervalScheduler
from ..orchestration import AnalysisOrchestrator
from ..persistence import IdempotencyConflict, SQLitePersistence
from ..runtime import ProductionRuntime, build_production_runtime

log = structlog.get_logger("repo_health.api")


class RepositoryRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_id: str
    canonical_uri: str
    provider: str = "sourcecraft"
    ref: str = "HEAD"
    head_sha: str | None = None


class AnalysisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: RepositoryRegistration
    requested_analyzer_ids: tuple[str, ...] = ()
    mode: str = "full"
    as_of: datetime | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)
    timeout_seconds: float | None = Field(default=None, gt=0, le=86_400)


class ScheduledAnalysisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: RepositoryRegistration
    interval_seconds: float = Field(gt=0, le=86_400)
    requested_analyzer_ids: tuple[str, ...] = ()
    mode: str = "full"


def _to_repository_ref(body: RepositoryRegistration) -> RepositoryRef:
    """Convert the API DTO into the strict domain contract without leaking 500s."""

    try:
        return RepositoryRef(**body.model_dump(exclude_none=True))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid repository reference") from exc


def create_app(
    *, orchestrator: AnalysisOrchestrator | None = None, persistence: SQLitePersistence | None = None
) -> FastAPI:
    owned_runtime = orchestrator is None
    runtime: ProductionRuntime | None = None
    if orchestrator is None:
        runtime = build_production_runtime(mode="api")
        orchestrator = runtime.orchestrator
        persistence = runtime.persistence
    assert orchestrator is not None
    store = persistence or orchestrator.persistence
    config = runtime.config if runtime is not None else RuntimeConfig.from_environment()
    scheduler = IntervalScheduler()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await scheduler.shutdown()
        if owned_runtime and runtime is not None:
            runtime.close()

    app = FastAPI(title="SourceCraft Repository Health Analyzer", version="repo-health-api-v1", lifespan=lifespan)
    app.state.orchestrator = orchestrator
    app.state.persistence = store
    app.state.scheduler = scheduler
    app.state.runtime = runtime

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or f"corr-{uuid.uuid4().hex}"
        request.state.correlation_id = correlation_id
        started = asyncio.get_running_loop().time()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("api_request_failed", correlation_id=correlation_id, route=request.url.path)
            raise
        response.headers["X-Correlation-ID"] = correlation_id
        log.info(
            "api_request_finished",
            correlation_id=correlation_id,
            route=request.url.path,
            method=request.method,
            status=response.status_code,
            duration_ms=int((asyncio.get_running_loop().time() - started) * 1000),
        )
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "repo-health-api"}

    @app.get("/readyz")
    async def readyz() -> dict[str, Any]:
        capabilities = (
            runtime.public_capabilities()
            if runtime is not None
            else {item.engine: item.public_dict() for item in config.capability_report()}
        )
        sourcecraft = capabilities.get("sourcecraft", {})
        return {
            "status": "ready",
            "service": "repo-health-api",
            "degraded": any(item["state"] != "available" for item in capabilities.values()),
            "capabilities": capabilities,
            "sourcecraft": {
                "configured": sourcecraft.get("configured", config.sourcecraft_url is not None),
                "token_present": config.sourcecraft_token_present,
                "state": sourcecraft.get("state", "unavailable"),
            },
        }

    @app.post("/repositories", status_code=status.HTTP_201_CREATED)
    async def register_repository(body: RepositoryRegistration) -> dict[str, Any]:
        repository = _to_repository_ref(body)
        try:
            record = store.register_repository(repository)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail="repository identity conflict") from exc
        return {"repository": record.repository.model_dump(mode="json"), "created_at": record.created_at.isoformat()}

    async def _run_background(request_contract: AnalysisRequest, checkout_path: Path) -> None:
        try:
            await orchestrator.analyze(request_contract, checkout_path=checkout_path)
        except Exception as exc:
            log.exception(
                "background_analysis_failed", analysis_id=request_contract.analysis_id, error_type=type(exc).__name__
            )

    @app.post("/analyses", status_code=status.HTTP_202_ACCEPTED)
    async def create_analysis(body: AnalysisCreate, background: BackgroundTasks) -> dict[str, Any]:
        as_of = body.as_of or datetime.now(UTC)
        request_contract = AnalysisRequest(
            repository=_to_repository_ref(body.repository),
            requested_analyzer_ids=body.requested_analyzer_ids,
            mode=body.mode,
            as_of=as_of,
            config_digest=config.digest(),
            idempotency_key=body.idempotency_key,
            timeout_seconds=body.timeout_seconds,
        )
        try:
            record = orchestrator.start(request_contract)
        except Exception as exc:
            if type(exc).__name__ == "IdempotencyConflict":
                raise HTTPException(status_code=409, detail="idempotency key conflict") from exc
            if isinstance(exc, ValueError):
                raise HTTPException(status_code=422, detail="invalid analysis request") from exc
            raise
        root = Path(config.checkout_root).resolve()
        checkout = root / request_contract.repository.repository_id.replace("/", "_")
        background.add_task(_run_background, request_contract, checkout)
        return {
            "analysis_id": record.analysis_id,
            "status": record.envelope.status.model_dump(mode="json"),
            "correlation_id": "see X-Correlation-ID",
        }

    @app.get("/analyses/{analysis_id}")
    async def analysis_status(analysis_id: str):
        record = store.get_analysis(analysis_id)
        if record is None:
            raise HTTPException(status_code=404, detail="analysis not found")
        return record.envelope.status.model_dump(mode="json")

    @app.get("/analyses/{analysis_id}/result")
    async def analysis_result(analysis_id: str):
        record = store.get_analysis(analysis_id)
        if record is None:
            raise HTTPException(status_code=404, detail="analysis not found")
        if record.envelope.score is None:
            return JSONResponse(status_code=202, content=record.envelope.status.model_dump(mode="json"))
        return record.envelope.score.model_dump(mode="json")

    @app.get("/integrations/sourcecraft/status")
    async def sourcecraft_status() -> dict[str, Any]:
        capabilities = (
            runtime.public_capabilities()
            if runtime is not None
            else {item.engine: item.public_dict() for item in config.capability_report()}
        )
        sourcecraft = capabilities.get("sourcecraft", {})
        return {
            "provider": "sourcecraft",
            "configured": sourcecraft.get("configured", config.sourcecraft_url is not None),
            "credential_source": "environment",
            "token_present": config.sourcecraft_token_present,
            "state": sourcecraft.get("state", "unavailable"),
            "reason": sourcecraft.get("reason", "SourceCraft capability was not detected"),
        }

    @app.get("/scheduler/status")
    async def scheduler_status() -> dict[str, Any]:
        return scheduler.status()

    @app.post("/scheduler/analyses", status_code=status.HTTP_202_ACCEPTED)
    async def schedule_analysis(body: ScheduledAnalysisCreate) -> dict[str, Any]:
        job_name = f"analysis-{uuid.uuid4().hex}"
        root = Path(config.checkout_root).resolve()
        checkout = root / body.repository.repository_id.replace("/", "_")

        async def scheduled_run() -> None:
            try:
                request_contract = AnalysisRequest(
                    repository=_to_repository_ref(body.repository),
                    requested_analyzer_ids=body.requested_analyzer_ids,
                    mode=body.mode,
                    as_of=datetime.now(UTC),
                    idempotency_key=f"{job_name}-{uuid.uuid4().hex}",
                    config_digest=config.digest(),
                )
                orchestrator.start(request_contract)
                await orchestrator.analyze(request_contract, checkout_path=checkout)
            except Exception as exc:
                log.exception("scheduled_analysis_failed", job_name=job_name, error_type=type(exc).__name__)

        try:
            scheduler.add_interval(scheduled_run, seconds=body.interval_seconds, name=job_name)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="scheduler job already exists") from exc
        return {"job_name": job_name, "interval_seconds": body.interval_seconds, "status": scheduler.status()}

    return app


app = create_app()


__all__ = ["AnalysisCreate", "RepositoryRegistration", "ScheduledAnalysisCreate", "app", "create_app"]
