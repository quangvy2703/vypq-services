from fastapi import APIRouter
from vypq_contracts.gateway import ServiceInfo


def build_info_router(info: ServiceInfo) -> APIRouter:
    """Router `/v1/info` để gateway hỏi service tự mô tả mình.

    Plan A để capability trong `service.yaml` — chỉ đọc được khi đứng cùng máy.
    Gateway ở máy khác nên cần một đường HTTP.
    """
    router = APIRouter(prefix="/v1")

    @router.get("/info", response_model=ServiceInfo)
    async def get_info() -> ServiceInfo:
        return info

    return router
