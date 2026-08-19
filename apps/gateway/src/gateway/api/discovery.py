from datetime import UTC, datetime

from fastapi import APIRouter
from vypq_core.host_registry import DiscoveryResponse

from gateway.db.repo import HostRepo
from gateway.settings import GatewaySettings


def build_discovery_router(session_factory, settings: GatewaySettings) -> APIRouter:
    router = APIRouter(prefix="/v1/discovery")

    @router.get("/hosts", response_model=DiscoveryResponse)
    async def hosts() -> DiscoveryResponse:
        # Kiểm hạn LÚC ĐỌC: poller treo thì cờ healthy trong DB đóng băng ở
        # giá trị cuối, và gateway sẽ phát một máy đã chết cho mọi service.
        # list_all_refs() tính lại độ tươi (kể cả chặn lệch đồng hồ) và đọc
        # state + token trong một truy vấn duy nhất — xem docstring của nó.
        now = datetime.now(UTC)
        async with session_factory() as session:
            refs = await HostRepo(session).list_all_refs(now=now, ttl_s=settings.host_ttl_s)
        return DiscoveryResponse(hosts=refs)

    return router
