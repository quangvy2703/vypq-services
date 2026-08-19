import uuid

from fastapi import APIRouter, File, Form, UploadFile
from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import InvokeMode, InvokeRequest, InvokeResponse
from vypq_core.errors import ServiceError

from gateway.proxy import SyncProxy


def build_invoke_router(proxy: SyncProxy, dispatcher=None) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.post("/invoke/upload", response_model=InvokeResponse)
    async def invoke_upload(
        service: str = Form(...),
        model_version: str | None = Form(default=None),
        file: UploadFile = File(...),  # noqa: B008
    ) -> InvokeResponse:
        record = await proxy.invoke(
            service, await file.read(), file.filename or "input", model_version
        )
        return InvokeResponse(
            trace_id=record.trace_id, mode=InvokeMode.SYNC,
            run_id=record.id, result=record.output,
        )

    @router.post("/invoke", response_model=InvokeResponse)
    async def invoke(request: InvokeRequest) -> InvokeResponse:
        if not request.input_uri:
            raise ServiceError(ErrorCode.BAD_INPUT, "thiếu input_uri", 422)
        if request.mode is InvokeMode.ASYNC:
            if dispatcher is None:
                raise ServiceError(
                    ErrorCode.BAD_INPUT, "gateway này chưa bật đường async", 501
                )
            trace = uuid.uuid4().hex
            await dispatcher.dispatch(request, trace)
            return InvokeResponse(trace_id=trace, mode=InvokeMode.ASYNC)

        data = await proxy.fetch(request.input_uri)
        record = await proxy.invoke(
            request.service, data, "input", request.model_version
        )
        return InvokeResponse(
            trace_id=record.trace_id, mode=InvokeMode.SYNC,
            run_id=record.id, result=record.output,
        )

    return router
