import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import InvokeMode, InvokeRequest, InvokeResponse
from vypq_core.errors import ServiceError

from gateway.auth import make_token_dependency
from gateway.proxy import SyncProxy
from gateway.settings import GatewaySettings


def build_invoke_router(
    proxy: SyncProxy, settings: GatewaySettings, dispatcher=None
) -> APIRouter:
    guard = Depends(make_token_dependency(settings.token))
    router = APIRouter(prefix="/v1", dependencies=[guard])

    @router.post("/invoke/upload", response_model=InvokeResponse)
    async def invoke_upload(
        request: Request,
        service: str = Form(...),
        model_version: str | None = Form(default=None),
        file: UploadFile = File(...),  # noqa: B008
    ) -> InvokeResponse:
        # Nhận trace_id của người gọi nếu có. Middleware đã echo header đó ra
        # response, nên nếu ở đây tự sinh UUID mới thì header, body, dòng runs và
        # lời gọi xuống service sẽ mang hai giá trị khác nhau — người vận hành
        # lần theo header sẽ không bao giờ tìm ra run.
        record = await proxy.invoke(
            service, await file.read(), file.filename or "input", model_version,
            trace_id=request.headers.get("x-trace-id"),
        )
        return InvokeResponse(
            trace_id=record.trace_id, mode=InvokeMode.SYNC,
            run_id=record.id, result=record.output,
        )

    @router.post("/invoke", response_model=InvokeResponse)
    async def invoke(raw_request: Request, request: InvokeRequest) -> InvokeResponse:
        if not request.input_uri:
            raise ServiceError(ErrorCode.BAD_INPUT, "thiếu input_uri", 422)
        inbound_trace_id = raw_request.headers.get("x-trace-id")
        if request.mode is InvokeMode.ASYNC:
            if dispatcher is None:
                raise ServiceError(
                    ErrorCode.BAD_INPUT, "gateway này chưa bật đường async", 501
                )
            trace = inbound_trace_id or uuid.uuid4().hex
            await dispatcher.dispatch(request, trace)
            return InvokeResponse(trace_id=trace, mode=InvokeMode.ASYNC)

        data = await proxy.fetch(request.input_uri)
        record = await proxy.invoke(
            request.service, data, "input", request.model_version,
            trace_id=inbound_trace_id,
        )
        return InvokeResponse(
            trace_id=record.trace_id, mode=InvokeMode.SYNC,
            run_id=record.id, result=record.output,
        )

    return router
