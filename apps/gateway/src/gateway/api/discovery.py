from datetime import UTC, datetime

from fastapi import APIRouter
from vypq_core.host_registry import DiscoveryResponse, HostRef

from gateway.db.repo import HostRepo
from gateway.settings import GatewaySettings


def build_discovery_router(session_factory, settings: GatewaySettings) -> APIRouter:
    router = APIRouter(prefix="/v1/discovery")

    @router.get("/hosts", response_model=DiscoveryResponse)
    async def hosts() -> DiscoveryResponse:
        now = datetime.now(UTC)
        async with session_factory() as session:
            repo = HostRepo(session)
            states = await repo.list_all()
            refs: list[HostRef] = []
            for state in states:
                # Kiểm hạn LÚC ĐỌC: poller treo thì cờ healthy trong DB đóng
                # băng ở giá trị cuối, và gateway sẽ phát một máy đã chết cho
                # mọi service. Tính lại ở đây khiến poller hỏng biểu hiện thành
                # "không có host nào", chứ không phải "mọi host đều khoẻ".
                fresh = (
                    state.last_seen_at is not None
                    and (now - state.last_seen_at).total_seconds() <= settings.host_ttl_s
                )
                refs.append(
                    HostRef(
                        name=state.name,
                        url=state.url,
                        token=await repo.token_for(state.name),
                        models=state.models,
                        healthy=state.healthy and fresh,
                    )
                )
        return DiscoveryResponse(hosts=refs)

    return router
