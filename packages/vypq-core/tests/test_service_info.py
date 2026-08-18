import httpx
from vypq_contracts.common import Task
from vypq_contracts.gateway import ServiceInfo
from vypq_core.app import create_app
from vypq_core.config import BaseServiceSettings
from vypq_core.service_info import build_info_router

INFO = ServiceInfo(
    name="ocr", task=Task.OCR, capability_input="image",
    capability_output="text_boxes", version="0.1.0", invoke_path="/v1/ocr",
    default_model="m1",
)


def _client() -> httpx.AsyncClient:
    app = create_app(
        BaseServiceSettings(service_name="ocr", version="0.1.0"),
        routers=[build_info_router(INFO)],
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_info_endpoint_returns_the_manifest():
    async with _client() as c:
        resp = await c.get("/v1/info")
    assert resp.status_code == 200
    assert resp.json() == INFO.model_dump(mode="json")


async def test_info_is_not_authenticated():
    # Service nằm trong mạng nội bộ sau gateway; /v1/info không có bí mật gì.
    async with _client() as c:
        assert (await c.get("/v1/info")).status_code == 200
