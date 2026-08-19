import httpx
from asr_service.backend.fake import FakeAsrBackend
from asr_service.handler import AsrHandler
from asr_service.main import build_app_with
from asr_service.settings import AsrSettings
from vypq_contracts.asr import RawAsrOutput


def _app(backend):
    settings = AsrSettings(service_name="asr", default_model="m1")
    return build_app_with(AsrHandler(backend, default_model=settings.default_model), settings)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_service_advertises_its_capability():
    # Gateway dựa vào đây để biết service nhận gì, trả gì, và model mặc định.
    # Đây là hợp đồng HTTP duy nhất giữa asr và gateway — không test thì một
    # invoke_path sai lệch sẽ chỉ lộ ra khi gateway gọi thật và nhận 404.
    async with _client(_app(FakeAsrBackend(RawAsrOutput()))) as c:
        resp = await c.get("/v1/info")
    body = resp.json()
    assert body["name"] == "asr"
    assert body["task"] == "asr"
    assert body["capability_input"] == "audio"
    assert body["invoke_path"] == "/v1/asr"
    assert body["default_model"] == "m1"
