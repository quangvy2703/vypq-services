import httpx
import pytest
from model_host.api.routes import build_router
from model_host.registry import ModelRegistry
from model_host.runners.fake import FakeOcrRunner
from model_host.settings import ModelHostSettings
from model_host.spec import HostConfig, ModelSpec
from vypq_contracts.common import ModelKind, Task
from vypq_core.app import create_app

TOKEN = "sekret"


def _app():
    config = HostConfig(
        host_name="gpu-1", vram_budget_mb=5000,
        models=[ModelSpec(id="m1", task=Task.OCR, kind=ModelKind.OPENSOURCE,
                          runner="fake", vram_mb=1000)],
    )
    registry = ModelRegistry(config, runners={"fake": FakeOcrRunner})
    settings = ModelHostSettings(service_name="model-host", token=TOKEN, host_name="gpu-1")
    return create_app(settings, routers=[build_router(registry, settings)])


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://t",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


async def test_models_endpoint_lists_declared_models():
    async with _client() as c:
        resp = await c.get("/v1/models")
    body = resp.json()
    assert resp.status_code == 200
    assert body["host_name"] == "gpu-1"
    assert [m["id"] for m in body["models"]] == ["m1"]


async def test_request_without_token_is_rejected():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t"
    ) as c:
        resp = await c.get("/v1/models")
    assert resp.status_code == 401


async def test_request_with_wrong_token_is_rejected():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://t",
        headers={"Authorization": "Bearer sai"},
    ) as c:
        resp = await c.get("/v1/models")
    assert resp.status_code == 401


async def test_health_does_not_require_token():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t"
    ) as c:
        resp = await c.get("/health")
    assert resp.status_code == 200


async def test_infer_upload_returns_raw_boxes():
    async with _client() as c:
        resp = await c.post(
            "/v1/infer/upload",
            data={"model_id": "m1"},
            files={"file": ("a.jpg", b"\xff\xd8fake-jpeg", "image/jpeg")},
        )
    body = resp.json()
    assert resp.status_code == 200
    assert body["model_id"] == "m1"
    assert body["task"] == "ocr"
    assert body["output"]["boxes"][0]["text"] == "XIN CHÀO"
    assert body["timing"]["infer_ms"] >= 0


async def test_infer_upload_with_unknown_model_returns_404_envelope():
    async with _client() as c:
        resp = await c.post(
            "/v1/infer/upload",
            data={"model_id": "khong-co"},
            files={"file": ("a.jpg", b"x", "image/jpeg")},
        )
    assert resp.status_code == 404
    assert resp.json()["code"] == "model_unavailable"


async def test_infer_by_uri_reads_local_file(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"\xff\xd8fake-jpeg")
    async with _client() as c:
        resp = await c.post(
            "/v1/infer", json={"model_id": "m1", "input_uri": image.as_uri()}
        )
    assert resp.status_code == 200
    assert resp.json()["output"]["boxes"][1]["text"] == "thế giới"


async def test_infer_by_uri_rejects_unsupported_scheme():
    async with _client() as c:
        resp = await c.post(
            "/v1/infer", json={"model_id": "m1", "input_uri": "s3://bucket/a.jpg"}
        )
    assert resp.status_code == 400
    assert "scheme" in resp.json()["message"]


def test_settings_refuse_empty_token():
    with pytest.raises(ValueError):
        ModelHostSettings(service_name="model-host", token="", host_name="gpu-1")
