from fastapi import APIRouter, Depends, Query
from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import RunRecord, RunsResponse, RunStatus
from vypq_core.errors import ServiceError

from gateway.auth import make_token_dependency
from gateway.db.repo import RunRepo
from gateway.settings import GatewaySettings


def build_runs_router(session_factory, settings: GatewaySettings) -> APIRouter:
    guard = Depends(make_token_dependency(settings.token))
    router = APIRouter(prefix="/v1", dependencies=[guard])

    @router.get("/runs", response_model=RunsResponse)
    async def list_runs(
        trace_id: str | None = None,
        service: str | None = None,
        status: RunStatus | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> RunsResponse:
        async with session_factory() as session:
            runs, total = await RunRepo(session).list_runs(
                trace_id=trace_id, service=service, status=status,
                limit=limit, offset=offset,
            )
        return RunsResponse(runs=runs, total=total)

    @router.get("/runs/{run_id}", response_model=RunRecord)
    async def get_run(run_id: str) -> RunRecord:
        async with session_factory() as session:
            run = await RunRepo(session).get(run_id)
        if run is None:
            raise ServiceError(ErrorCode.BAD_INPUT, f"không có run '{run_id}'", 404)
        return run

    return router
