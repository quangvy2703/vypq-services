from fastapi import APIRouter, Response
from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import HostRegistration, HostsResponse, HostState
from vypq_core.errors import ServiceError

from gateway.db.repo import HostRepo
from gateway.settings import GatewaySettings


def build_hosts_router(session_factory, settings: GatewaySettings) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.post("/hosts", response_model=HostState, status_code=201)
    async def register(reg: HostRegistration) -> HostState:
        async with session_factory() as session:
            return await HostRepo(session).upsert(reg)

    @router.get("/hosts", response_model=HostsResponse)
    async def list_hosts() -> HostsResponse:
        async with session_factory() as session:
            return HostsResponse(hosts=await HostRepo(session).list_all())

    @router.delete("/hosts/{name}", status_code=204)
    async def delete_host(name: str) -> Response:
        async with session_factory() as session:
            if not await HostRepo(session).delete(name):
                raise ServiceError(
                    ErrorCode.BAD_INPUT, f"không có host tên '{name}'", http_status=404
                )
        return Response(status_code=204)

    return router
