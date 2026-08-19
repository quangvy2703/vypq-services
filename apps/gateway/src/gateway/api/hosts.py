from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import HostRegistration, HostsResponse, HostState
from vypq_core.errors import ServiceError

from gateway.auth import make_token_dependency
from gateway.db.repo import HostRepo
from gateway.settings import GatewaySettings


def build_hosts_router(session_factory, settings: GatewaySettings) -> APIRouter:
    # POST /v1/hosts cho phép trỏ lại một host đang thuê sang bất kỳ URL nào —
    # đúng lỗ hổng khiến review tổng B1 yêu cầu thay đổi này. Không có ngoại lệ
    # tokenless ở đây nữa: /v1/hosts (GET, không token trong response) chỉ khác
    # /v1/discovery/hosts (có token) ở NỘI DUNG trả về, không phải ở việc ai
    # được gọi.
    guard = Depends(make_token_dependency(settings.token))
    router = APIRouter(prefix="/v1", dependencies=[guard])

    @router.post("/hosts", response_model=HostState, status_code=201)
    async def register(reg: HostRegistration) -> HostState:
        async with session_factory() as session:
            return await HostRepo(session).upsert(reg)

    @router.get("/hosts", response_model=HostsResponse)
    async def list_hosts() -> HostsResponse:
        # Tính lại độ tươi giống hệt /v1/discovery/hosts (xem
        # HostRepo.list_all_states docstring): dashboard không được nói dối
        # rằng một host quá hạn (poller treo) vẫn khoẻ trong khi mọi service
        # định tuyến qua đường kia đã coi nó là chết.
        now = datetime.now(UTC)
        async with session_factory() as session:
            hosts = await HostRepo(session).list_all_states(now=now, ttl_s=settings.host_ttl_s)
        return HostsResponse(hosts=hosts)

    @router.delete("/hosts/{name}", status_code=204)
    async def delete_host(name: str) -> Response:
        async with session_factory() as session:
            if not await HostRepo(session).delete(name):
                raise ServiceError(
                    ErrorCode.BAD_INPUT, f"không có host tên '{name}'", http_status=404
                )
        return Response(status_code=204)

    return router
