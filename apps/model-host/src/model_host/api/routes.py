import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile
from vypq_contracts.common import ErrorCode
from vypq_contracts.hosting import InferRequest, InferResponse, InferTiming, ModelsResponse
from vypq_core.errors import ServiceError

from model_host.auth import make_token_dependency
from model_host.registry import ModelRegistry
from model_host.settings import ModelHostSettings

_SUPPORTED_SCHEMES = {"http", "https", "file"}


async def _fetch(uri: str, *, allow_file: bool, max_bytes: int) -> bytes:
    scheme = urlparse(uri).scheme
    if scheme not in _SUPPORTED_SCHEMES:
        raise ServiceError(
            ErrorCode.BAD_INPUT,
            f"scheme '{scheme}' chưa hỗ trợ — dùng http(s) presigned url hoặc file://",
            http_status=400,
        )
    if scheme == "file":
        if not allow_file:
            raise ServiceError(
                ErrorCode.BAD_INPUT,
                "file:// bị tắt trên host này — bật bằng VYPQ_ALLOW_FILE_URI nếu chạy local",
                http_status=400,
            )
        path = Path(urlparse(uri).path)
        if not path.is_file():
            raise ServiceError(ErrorCode.BAD_INPUT, f"không thấy file {path}", 400)
        return path.read_bytes()

    # Đọc theo luồng và cắt khi vượt hạn: `response.content` nạp nguyên body vào
    # RAM, nên một URI trỏ tới file khổng lồ đủ để hạ cả máy GPU.
    chunks: list[bytes] = []
    total = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream("GET", uri) as response:
            if response.status_code >= 400:
                raise ServiceError(ErrorCode.BAD_INPUT, f"tải {uri} thất bại", 400)
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ServiceError(
                        ErrorCode.BAD_INPUT,
                        f"input vượt quá {max_bytes // 1024 // 1024}MB",
                        http_status=413,
                    )
                chunks.append(chunk)
    return b"".join(chunks)


def build_router(registry: ModelRegistry, settings: ModelHostSettings) -> APIRouter:
    guard = Depends(make_token_dependency(settings.token))
    router = APIRouter(prefix="/v1", dependencies=[guard])

    def _run(model_id: str, data: bytes, params: dict) -> InferResponse:
        runner, spec, load_ms = registry.acquire(model_id)
        started = time.monotonic()
        output = runner.predict(data, {**spec.params, **params})
        infer_ms = int((time.monotonic() - started) * 1000)
        return InferResponse(
            model_id=model_id,
            task=spec.task,
            output=output,
            timing=InferTiming(load_ms=load_ms, infer_ms=infer_ms),
        )

    @router.get("/models", response_model=ModelsResponse)
    async def list_models() -> ModelsResponse:
        return ModelsResponse(host_name=registry.host_name, models=registry.infos())

    @router.post("/infer", response_model=InferResponse)
    async def infer(request: InferRequest) -> InferResponse:
        if not request.input_uri:
            raise ServiceError(ErrorCode.BAD_INPUT, "thiếu input_uri", 400)
        data = await _fetch(
            request.input_uri,
            allow_file=settings.allow_file_uri,
            max_bytes=settings.max_download_mb * 1024 * 1024,
        )
        return _run(request.model_id, data, request.params)

    @router.post("/infer/upload", response_model=InferResponse)
    async def infer_upload(
        model_id: str = Form(...), file: UploadFile = File(...)  # noqa: B008
    ) -> InferResponse:
        return _run(model_id, await file.read(), {})

    return router
