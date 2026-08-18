from fastapi import APIRouter
from vypq_contracts.gateway import ServiceInfo


def build_info_router(info: ServiceInfo) -> APIRouter:
    """Router `/v1/info` để gateway hỏi service tự mô tả mình.

    Gateway chạy trên máy khác, không đọc được file cấu hình nằm cạnh service —
    nó cần một đường HTTP để hỏi trực tiếp service đang chạy. `info` là nguồn
    sự thật sống: khai ở đây và trả nguyên qua HTTP, không lệch với route thật
    mà chính service này đăng ký.
    """
    router = APIRouter(prefix="/v1")

    @router.get("/info", response_model=ServiceInfo)
    async def get_info() -> ServiceInfo:
        return info

    return router
