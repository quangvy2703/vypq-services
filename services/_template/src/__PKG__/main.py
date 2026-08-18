from contextlib import asynccontextmanager

from fastapi import APIRouter, File, Form, Request, UploadFile
from vypq_contracts.common import HealthStatus, Task
from vypq_contracts.gateway import ServiceInfo
from vypq_contracts.__TASK__ import __RESP__
from vypq_core.app import create_app
from vypq_core.host_registry import StaticHostRegistry
from vypq_core.logging import get_trace_id
from vypq_core.service_info import build_info_router

from __PKG__.backend.remote import Remote__BACKEND__
from __PKG__.handler import __HANDLER__
from __PKG__.settings import __SETTINGS__, load_hosts


def build_app_with(handler: __HANDLER__, settings: __SETTINGS__, backend=None, lifespan=None):
    router = APIRouter(prefix="/v1")

    @router.post("/__TASK__", response_model=__RESP__)
    async def __TASK__(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
        model_version: str | None = Form(default=None),
    ) -> __RESP__:
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
        task=Task.__TASKUPPER__,
        capability_input="bytes",
        capability_output="json",
        version=settings.version,
        invoke_path="/v1/__TASK__",
        default_model=settings.default_model,
    )

    return create_app(
        settings,
        routers=[router, build_info_router(info)],
        readiness={"model_host": _upstream_ready},
        lifespan=lifespan,
    )


def build_app():
    settings = __SETTINGS__()
    registry = StaticHostRegistry(load_hosts(settings.hosts_path))
    backend = Remote__BACKEND__(registry, timeout_s=settings.timeout_s)
    handler = __HANDLER__(backend, default_model=settings.default_model)

    @asynccontextmanager
    async def _lifespan(_app):
        yield
        # Không đóng thì các connection httpx của mỗi host treo tới khi tiến trình
        # chết — với worker chạy dài (Task 12) đó là rò tài nguyên thật.
        await backend.aclose()

    return build_app_with(handler, settings, backend=backend, lifespan=_lifespan)


app = build_app()
