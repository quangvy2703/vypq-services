from contextlib import asynccontextmanager

from fastapi import APIRouter, File, Form, Request, UploadFile
from vypq_contracts.common import HealthStatus, Task
from vypq_contracts.gateway import ServiceInfo
from vypq_contracts.ocr import OcrResponse
from vypq_core.app import create_app
from vypq_core.logging import get_trace_id
from vypq_core.metrics import build_metrics_router
from vypq_core.service_info import build_info_router

from ocr_service.backend.remote import RemoteOcrBackend
from ocr_service.handler import OcrHandler
from ocr_service.settings import OcrSettings, build_host_registry


def build_app_with(handler: OcrHandler, settings: OcrSettings, backend=None, lifespan=None):
    router = APIRouter(prefix="/v1")

    @router.post("/ocr", response_model=OcrResponse)
    async def ocr(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
        model_version: str | None = Form(default=None),
    ) -> OcrResponse:
        trace_id = request.headers.get("x-trace-id") or get_trace_id()
        return await handler.run(await file.read(), model_version, trace_id)

    async def _upstream_ready() -> tuple[HealthStatus, str]:
        if backend is None:
            return HealthStatus.OK, "fake backend"
        open_hosts = backend.open_circuits()
        if open_hosts:
            return HealthStatus.DOWN, f"circuit đang mở: {', '.join(open_hosts)}"
        return HealthStatus.OK, "model-host phản hồi bình thường"

    info = ServiceInfo(
        name=settings.service_name,
        task=Task.OCR,
        capability_input="image",
        capability_output="text_boxes",
        version=settings.version,
        invoke_path="/v1/ocr",
        default_model=settings.default_model,
    )

    return create_app(
        settings,
        routers=[router, build_info_router(info), build_metrics_router()],
        readiness={"model_host": _upstream_ready},
        lifespan=lifespan,
    )


def build_app():
    settings = OcrSettings()
    registry = build_host_registry(settings)
    backend = RemoteOcrBackend(registry, timeout_s=settings.timeout_s)
    handler = OcrHandler(
        backend, default_model=settings.default_model, max_side=settings.max_side
    )

    @asynccontextmanager
    async def _lifespan(_app):
        yield
        # Không đóng thì các connection httpx của mỗi host treo tới khi tiến trình
        # chết — với worker chạy dài (Task 12) đó là rò tài nguyên thật.
        await backend.aclose()
        # DiscoveryHostRegistry giữ client httpx riêng để poll gateway; không
        # đóng thì client đó rò y hệt các client của backend ở trên.
        await registry.aclose()

    return build_app_with(handler, settings, backend=backend, lifespan=_lifespan)


app = build_app()
