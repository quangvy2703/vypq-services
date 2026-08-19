import httpx
import pytest
import respx
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.hosting import ModelInfo
from vypq_core.host_registry import (
    DiscoveryHostRegistry,
    HostRef,
    HostRegistry,
    NoHostAvailableError,
)

URL = "http://gateway:8080/v1/discovery/hosts"


def _body(*hosts: dict) -> dict:
    return {"hosts": list(hosts)}


def _host(name: str, healthy: bool = True, model: str = "m1") -> dict:
    return {
        "name": name, "url": f"http://{name}:9000", "token": "t", "healthy": healthy,
        "inflight": 0,
        "models": [
            {"id": model, "task": "ocr", "kind": "opensource", "runner": "paddle",
             "loaded": False, "available": True, "vram_mb": 0}
        ],
    }


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


@respx.mock
async def test_fetches_hosts_from_the_gateway():
    respx.get(URL).mock(return_value=httpx.Response(200, json=_body(_host("a"))))
    reg = DiscoveryHostRegistry(URL)
    assert [h.name for h in await reg.hosts()] == ["a"]
    await reg.aclose()


@respx.mock
async def test_result_is_cached_until_refresh_window_elapses():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=_body(_host("a"))))
    clock = Clock()
    reg = DiscoveryHostRegistry(URL, refresh_s=15.0, clock=clock)
    await reg.hosts()
    await reg.hosts()
    assert route.call_count == 1          # trong cửa sổ thì không hỏi lại
    clock.now = 20.0
    await reg.hosts()
    assert route.call_count == 2
    await reg.aclose()


@respx.mock
async def test_new_host_appears_without_restarting_the_service():
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json=_body(_host("a"))),
            httpx.Response(200, json=_body(_host("a"), _host("b"))),
        ]
    )
    clock = Clock()
    reg = DiscoveryHostRegistry(URL, refresh_s=15.0, clock=clock)
    assert len(await reg.hosts()) == 1
    clock.now = 20.0
    assert len(await reg.hosts()) == 2
    assert route.call_count == 2
    await reg.aclose()


@respx.mock
async def test_gateway_down_keeps_serving_the_last_known_list():
    # Gateway sập KHÔNG được kéo theo mọi service. Danh sách cũ vẫn tốt hơn
    # danh sách rỗng: host trong đó có thể vẫn đang chạy bình thường.
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json=_body(_host("a"))),
            httpx.ConnectError("gateway chết"),
        ]
    )
    clock = Clock()
    reg = DiscoveryHostRegistry(URL, refresh_s=15.0, clock=clock)
    await reg.hosts()
    clock.now = 20.0
    assert [h.name for h in await reg.hosts()] == ["a"]
    await reg.aclose()


@respx.mock
async def test_first_fetch_failing_falls_back_to_static_list():
    respx.get(URL).mock(side_effect=httpx.ConnectError("gateway chưa lên"))
    fallback = [HostRef(name="du-phong", url="http://d:9000",
                        models=[ModelInfo(id="m1", task=Task.OCR,
                                          kind=ModelKind.OPENSOURCE, runner="p")])]
    reg = DiscoveryHostRegistry(URL, fallback=fallback)
    assert (await reg.pick("m1")).name == "du-phong"
    await reg.aclose()


@respx.mock
async def test_pick_skips_unhealthy_hosts_from_the_gateway():
    respx.get(URL).mock(
        return_value=httpx.Response(200, json=_body(_host("a", healthy=False), _host("b")))
    )
    reg = DiscoveryHostRegistry(URL)
    assert (await reg.pick("m1")).name == "b"
    await reg.aclose()


@respx.mock
async def test_pick_raises_when_nothing_serves_the_model():
    respx.get(URL).mock(return_value=httpx.Response(200, json=_body(_host("a"))))
    reg = DiscoveryHostRegistry(URL)
    with pytest.raises(NoHostAvailableError):
        await reg.pick("khong-co")
    await reg.aclose()


@respx.mock
async def test_lease_tracks_inflight_across_refreshes():
    # inflight sống ở đối tượng HostRef. Refresh dựng HostRef mới thì số đang
    # chạy bị xoá sạch và pick() lại dồn tải. Phải chuyển tiếp qua các lần làm mới.
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=_body(_host("a"))))
    clock = Clock()
    reg = DiscoveryHostRegistry(URL, refresh_s=15.0, clock=clock)
    host = await reg.pick("m1")
    async with reg.lease(host):
        clock.now = 20.0
        refreshed = await reg.hosts()
        assert refreshed[0].inflight == 1
    assert route.call_count == 2
    assert (await reg.hosts())[0].inflight == 0
    await reg.aclose()


async def test_satisfies_the_protocol():
    assert isinstance(DiscoveryHostRegistry(URL), HostRegistry)
