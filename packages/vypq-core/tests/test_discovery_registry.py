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


@respx.mock
async def test_host_object_is_updated_in_place_on_refresh():
    # Máy GPU thuê theo giờ: giữ nguyên tên nhưng đổi URL ngrok và token mỗi
    # lần thuê lại. Registry phải giữ nguyên đối tượng HostRef (để lease() đang
    # mở không bị lạc sang bản mới) NHƯNG vẫn phải ghi đè url/token bằng giá
    # trị mới nhất — giữ đối tượng mà quên cập nhật giá trị thì còn tệ hơn cả
    # bug inflight mà nó sửa, vì service sẽ tiếp tục gọi vào một tunnel không
    # còn tồn tại nữa.
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json=_body(_host("a"))),
            httpx.Response(
                200,
                json=_body({**_host("a"), "url": "http://a-moi:7000", "token": "token-moi"}),
            ),
        ]
    )
    clock = Clock()
    reg = DiscoveryHostRegistry(URL, refresh_s=15.0, clock=clock)
    before = await reg.pick("m1")
    clock.now = 20.0
    refreshed = await reg.hosts()
    assert refreshed[0] is before  # cùng đối tượng: lease() đang mở không bị lạc

    after = await reg.pick("m1")
    assert after.url == "http://a-moi:7000"
    assert after.token == "token-moi"
    assert route.call_count == 2
    await reg.aclose()


@respx.mock
async def test_host_removed_from_gateway_response_is_dropped():
    # Máy thuê theo giờ hết hạn thuê thì biến mất hẳn khỏi danh sách gateway
    # trả về. Registry phải bỏ nó ra khỏi cache, không được giữ lại làm host
    # "ma" — nếu không, pick() sẽ tiếp tục định tuyến việc vào một máy không
    # còn thuê nữa, dẫn tới lỗi kết nối thay vì lỗi định tuyến sạch.
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json=_body(_host("a", model="m1"), _host("b", model="m2"))),
            httpx.Response(200, json=_body(_host("b", model="m2"))),
        ]
    )
    clock = Clock()
    reg = DiscoveryHostRegistry(URL, refresh_s=15.0, clock=clock)
    await reg.hosts()
    clock.now = 20.0
    remaining = await reg.hosts()
    assert [h.name for h in remaining] == ["b"]
    with pytest.raises(NoHostAvailableError):
        await reg.pick("m1")
    assert route.call_count == 2
    await reg.aclose()


@respx.mock
async def test_first_fetch_failing_without_fallback_raises_domain_error():
    # Không cấu hình fallback mà để lộ thẳng ConnectError của httpx ra ngoài
    # thì caller không phân biệt được "model này hiện không có host nào phục
    # vụ" với "bản thân registry đang hỏng" — cả hai tình huống phải quy về
    # cùng một domain error để service xử lý thống nhất.
    respx.get(URL).mock(side_effect=httpx.ConnectError("gateway chưa lên"))
    reg = DiscoveryHostRegistry(URL)
    with pytest.raises(NoHostAvailableError):
        await reg.pick("m1")
    await reg.aclose()
