import io

import httpx
from ocr_service.backend.fake import FakeOcrBackend
from ocr_service.handler import OcrHandler
from ocr_service.main import build_app_with
from ocr_service.settings import OcrSettings
from PIL import Image
from vypq_contracts.ocr import RawOcrOutput, TextBox


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buf, format="PNG")
    return buf.getvalue()


def _app(backend):
    settings = OcrSettings(service_name="ocr", default_model="m1")
    return build_app_with(OcrHandler(backend, default_model=settings.default_model), settings)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_post_ocr_returns_result():
    raw = RawOcrOutput(
        boxes=[TextBox(id=0, polygon=[(0, 0), (9, 0), (9, 9), (0, 9)], text="HÓA ĐƠN")]
    )
    async with _client(_app(FakeOcrBackend(raw))) as c:
        resp = await c.post("/v1/ocr", files={"file": ("a.png", _png(), "image/png")})
    body = resp.json()
    assert resp.status_code == 200
    assert body["result"]["full_text"] == "HÓA ĐƠN"
    assert body["model_version"] == "m1"


async def test_post_ocr_with_broken_file_returns_422_envelope():
    async with _client(_app(FakeOcrBackend(RawOcrOutput()))) as c:
        resp = await c.post("/v1/ocr", files={"file": ("a.png", b"rac", "image/png")})
    assert resp.status_code == 422
    assert resp.json()["code"] == "bad_input"


async def test_ready_reports_degraded_when_a_host_circuit_is_open():
    class _OpenBackend(FakeOcrBackend):
        def open_circuits(self) -> list[str]:
            return ["gpu-1"]

    settings = OcrSettings(service_name="ocr", default_model="m1")
    backend = _OpenBackend(RawOcrOutput())
    app = build_app_with(
        OcrHandler(backend, default_model=settings.default_model), settings, backend=backend
    )
    async with _client(app) as c:
        resp = await c.get("/ready")
    assert resp.status_code == 503
    assert "gpu-1" in resp.json()["detail"]["model_host"]


async def test_service_advertises_its_capability():
    # Gateway dựa vào đây để biết service nhận gì, trả gì, và model mặc định.
    async with _client(_app(FakeOcrBackend(RawOcrOutput()))) as c:
        resp = await c.get("/v1/info")
    body = resp.json()
    assert body["name"] == "ocr"
    assert body["task"] == "ocr"
    assert body["capability_input"] == "image"
    assert body["invoke_path"] == "/v1/ocr"
    assert body["default_model"] == "m1"


async def test_trace_id_header_is_echoed_back():
    async with _client(_app(FakeOcrBackend(RawOcrOutput()))) as c:
        resp = await c.post(
            "/v1/ocr",
            files={"file": ("a.png", _png(), "image/png")},
            headers={"x-trace-id": "trace-42"},
        )
    assert resp.headers["x-trace-id"] == "trace-42"
    assert resp.json()["trace_id"] == "trace-42"
