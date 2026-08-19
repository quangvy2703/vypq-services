import asyncio

import httpx
import pytest
import respx
from gateway.db.models import Base
from gateway.db.repo import HostRepo
from gateway.registry.poller import HostPoller
from gateway.settings import GatewaySettings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vypq_contracts.gateway import HostRegistration

MODELS_BODY = {
    "host_name": "gpu-1",
    "models": [
        {"id": "m1", "task": "ocr", "kind": "opensource", "runner": "paddle",
         "loaded": False, "available": True, "vram_mb": 2500},
    ],
}


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _register(factory, name="gpu-1", url="http://h:9000", token="t"):
    async with factory() as s:
        await HostRepo(s).upsert(HostRegistration(name=name, url=url, token=token))


def _poller(factory) -> HostPoller:
    return HostPoller(factory, GatewaySettings(service_name="gateway"))


@respx.mock
async def test_poll_marks_host_healthy_and_stores_models(factory):
    await _register(factory)
    respx.get("http://h:9000/v1/models").mock(return_value=httpx.Response(200, json=MODELS_BODY))
    assert await _poller(factory).poll_once() == 1
    async with factory() as s:
        state = await HostRepo(s).get("gpu-1")
    assert state.healthy is True
    assert [m.id for m in state.models] == ["m1"]


@respx.mock
async def test_poll_sends_the_host_token(factory):
    await _register(factory, token="bi-mat")
    captured = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=MODELS_BODY)

    respx.get("http://h:9000/v1/models").mock(side_effect=_record)
    await _poller(factory).poll_once()
    assert captured["auth"] == "Bearer bi-mat"


@respx.mock
async def test_unreachable_host_becomes_unhealthy_with_a_reason(factory):
    await _register(factory)
    respx.get("http://h:9000/v1/models").mock(side_effect=httpx.ConnectError("mất kết nối"))
    await _poller(factory).poll_once()
    async with factory() as s:
        state = await HostRepo(s).get("gpu-1")
    assert state.healthy is False
    assert "mất kết nối" in state.last_error


@respx.mock
async def test_wrong_token_marks_unhealthy_not_healthy(factory):
    # Máy thuê lại đổi token: host vẫn trả lời nhưng ta không dùng được nó.
    await _register(factory)
    respx.get("http://h:9000/v1/models").mock(return_value=httpx.Response(401))
    await _poller(factory).poll_once()
    async with factory() as s:
        assert (await HostRepo(s).get("gpu-1")).healthy is False


@respx.mock
async def test_one_dead_host_does_not_stop_the_others(factory):
    await _register(factory, name="gpu-1", url="http://a:9000")
    await _register(factory, name="gpu-2", url="http://b:9000")
    respx.get("http://a:9000/v1/models").mock(side_effect=httpx.ConnectError("chết"))
    respx.get("http://b:9000/v1/models").mock(
        return_value=httpx.Response(200, json=MODELS_BODY)
    )
    assert await _poller(factory).poll_once() == 2
    async with factory() as s:
        repo = HostRepo(s)
        assert (await repo.get("gpu-1")).healthy is False
        assert (await repo.get("gpu-2")).healthy is True


@respx.mock
async def test_malformed_models_body_marks_unhealthy(factory):
    # model-host phiên bản khác trả shape lạ: coi như không dùng được, không nổ.
    await _register(factory)
    respx.get("http://h:9000/v1/models").mock(
        return_value=httpx.Response(200, json={"khong": "dung shape"})
    )
    await _poller(factory).poll_once()
    async with factory() as s:
        state = await HostRepo(s).get("gpu-1")
    assert state.healthy is False
    assert state.last_error


async def test_poll_with_no_hosts_is_a_noop(factory):
    assert await _poller(factory).poll_once() == 0


@respx.mock
async def test_db_failure_on_one_host_does_not_stop_the_others(factory, monkeypatch):
    # gpu-1 sẽ hỏng lúc ghi DB (không phải lúc gọi HTTP); gpu-2 vẫn phải được
    # poll và ghi nhận bình thường, và poll_once() vẫn phải trả đủ số host.
    await _register(factory, name="gpu-1", url="http://a:9000")
    await _register(factory, name="gpu-2", url="http://b:9000")
    respx.get("http://a:9000/v1/models").mock(return_value=httpx.Response(200, json=MODELS_BODY))
    respx.get("http://b:9000/v1/models").mock(return_value=httpx.Response(200, json=MODELS_BODY))

    original_mark_polled = HostRepo.mark_polled

    async def _flaky_mark_polled(self, name, *args, **kwargs):
        if name == "gpu-1":
            raise RuntimeError("ghi DB hỏng")
        return await original_mark_polled(self, name, *args, **kwargs)

    monkeypatch.setattr(HostRepo, "mark_polled", _flaky_mark_polled)

    assert await _poller(factory).poll_once() == 2
    async with factory() as s:
        repo = HostRepo(s)
        assert (await repo.get("gpu-2")).healthy is True


@respx.mock
async def test_cancelled_error_in_one_host_propagates_out_of_poll_once(factory):
    # CancelledError là tín hiệu shutdown, không phải lỗi của host: nó phải
    # bay ra khỏi poll_once() thay vì bị nuốt, nếu không lifespan sẽ treo.
    await _register(factory, name="gpu-1", url="http://a:9000")
    await _register(factory, name="gpu-2", url="http://b:9000")
    respx.get("http://a:9000/v1/models").mock(return_value=httpx.Response(200, json=MODELS_BODY))
    respx.get("http://b:9000/v1/models").mock(return_value=httpx.Response(200, json=MODELS_BODY))

    poller = _poller(factory)
    original_poll_host = poller._poll_host

    async def _cancelling_poll_host(client, name, url):
        if name == "gpu-1":
            raise asyncio.CancelledError()
        return await original_poll_host(client, name, url)

    poller._poll_host = _cancelling_poll_host

    with pytest.raises(asyncio.CancelledError):
        await poller.poll_once()
