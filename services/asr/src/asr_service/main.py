from contextlib import asynccontextmanager

from fastapi import APIRouter, File, Form, Request, UploadFile
from vypq_contracts.asr import AsrResponse
from vypq_contracts.common import HealthStatus, Task
from vypq_contracts.gateway import ServiceInfo
from vypq_core.app import create_app
from vypq_core.host_registry import StaticHostRegistry
from vypq_core.logging import get_trace_id
from vypq_core.service_info import build_info_router

from asr_service.backend.remote import RemoteAsrBackend
from asr_service.handler import AsrHandler
from asr_service.settings import AsrSettings, load_hosts


def build_app_with(handler: AsrHandler, settings: AsrSettings, backend=None, lifespan=None):
    router = APIRouter(prefix="/v1")

    @router.post("/asr", response_model=AsrResponse)
    async def asr(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
        model_version: str | None = Form(default=None),
    ) -> AsrResponse:
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
        task=Task.ASR,
        capability_input="audio",
        capability_output="transcript",
        version=settings.version,
        invoke_path="/v1/asr",
        default_model=settings.default_model,
    )

    return create_app(
        settings,
        routers=[router, build_info_router(info)],
        readiness={"model_host": _upstream_ready},
        lifespan=lifespan,
    )


def build_app():
    settings = AsrSettings()
    registry = StaticHostRegistry(load_hosts(settings.hosts_path))
    backend = RemoteAsrBackend(registry, timeout_s=settings.timeout_s)
    handler = AsrHandler(backend, default_model=settings.default_model)

    @asynccontextmanager
    async def _lifespan(_app):
        yield
        # Không đóng thì các connection httpx của mỗi host treo tới khi tiến trình
        # chết — với worker chạy dài (Task 12) đó là rò tài nguyên thật.
        await backend.aclose()

    return build_app_with(handler, settings, backend=backend, lifespan=_lifespan)


app = build_app()
