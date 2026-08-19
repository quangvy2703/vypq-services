import pytest
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.hosting import ModelInfo
from vypq_core.host_registry import (
    HostRef,
    HostRegistry,
    NoHostAvailableError,
    StaticHostRegistry,
)


def _model(mid: str, task: Task = Task.OCR, available: bool = True) -> ModelInfo:
    return ModelInfo(
        id=mid, task=task, kind=ModelKind.OPENSOURCE, runner="fake", available=available
    )


def _host(name: str, models: list[ModelInfo], healthy: bool = True) -> HostRef:
    return HostRef(name=name, url=f"http://{name}:9000", models=models, healthy=healthy)


async def test_pick_returns_host_that_has_the_model():
    reg = StaticHostRegistry([_host("a", [_model("m1")]), _host("b", [_model("m2")])])
    assert (await reg.pick("m2")).name == "b"


async def test_pick_skips_unhealthy_hosts():
    reg = StaticHostRegistry(
        [_host("a", [_model("m1")], healthy=False), _host("b", [_model("m1")])]
    )
    assert (await reg.pick("m1")).name == "b"


async def test_pick_skips_hosts_where_model_is_unavailable():
    reg = StaticHostRegistry(
        [_host("a", [_model("m1", available=False)]), _host("b", [_model("m1")])]
    )
    assert (await reg.pick("m1")).name == "b"


async def test_pick_chooses_least_inflight():
    a = _host("a", [_model("m1")])
    b = _host("b", [_model("m1")])
    a.inflight = 3
    b.inflight = 1
    reg = StaticHostRegistry([a, b])
    assert (await reg.pick("m1")).name == "b"


async def test_pick_raises_when_no_host_has_the_model():
    reg = StaticHostRegistry([_host("a", [_model("m1")])])
    with pytest.raises(NoHostAvailableError):
        await reg.pick("khong-ton-tai")


async def test_lease_increments_then_decrements_inflight():
    host = _host("a", [_model("m1")])
    reg = StaticHostRegistry([host])
    async with reg.lease(host):
        assert host.inflight == 1
    assert host.inflight == 0


async def test_lease_decrements_even_when_body_raises():
    host = _host("a", [_model("m1")])
    reg = StaticHostRegistry([host])
    with pytest.raises(RuntimeError):
        async with reg.lease(host):
            raise RuntimeError("hỏng")
    assert host.inflight == 0


def test_static_registry_satisfies_the_protocol():
    # Nếu Protocol thiếu lease(), bản discovery ở Plan B có thể quên mà không ai biết.
    assert isinstance(StaticHostRegistry([]), HostRegistry)


async def test_static_registry_aclose_is_awaitable_and_harmless():
    # StaticHostRegistry không giữ client nào để đóng, nhưng caller đóng bất
    # kỳ registry nào mà không cần biết đang cầm bản static hay discovery —
    # aclose() phải tồn tại và không được ném lỗi.
    reg = StaticHostRegistry([_host("a", [_model("m1")])])
    await reg.aclose()


def test_models_for_task_marks_unavailable_when_only_unhealthy_hosts_have_it():
    reg = StaticHostRegistry([_host("a", [_model("m1")], healthy=False)])
    models = reg.models_for_task(Task.OCR)
    assert len(models) == 1                 # vẫn liệt kê để biết model tồn tại
    assert models[0].available is False      # nhưng không hứa là dùng được


async def test_catalogue_agrees_with_pick():
    # available=True phải tương đương "pick() sẽ thành công", không hơn không kém.
    reg = StaticHostRegistry(
        [_host("a", [_model("m1", available=False)]), _host("b", [_model("m1")], healthy=False)]
    )
    assert reg.models_for_task(Task.OCR)[0].available is False
    with pytest.raises(NoHostAvailableError):
        await reg.pick("m1")


def test_models_for_task_prefers_the_available_copy():
    reg = StaticHostRegistry(
        [_host("a", [_model("m1", available=False)]), _host("b", [_model("m1")])]
    )
    models = reg.models_for_task(Task.OCR)
    assert len(models) == 1
    assert models[0].available is True


async def test_models_for_task_filters_and_dedupes():
    reg = StaticHostRegistry(
        [
            _host("a", [_model("m1"), _model("m9", task=Task.ASR)]),
            _host("b", [_model("m1"), _model("m2")]),
        ]
    )
    ids = sorted(m.id for m in reg.models_for_task(Task.OCR))
    assert ids == ["m1", "m2"]


async def test_concurrent_leases_spread_across_hosts():
    # pick() đọc inflight, lease() mới tăng. `await` bên trong lease mô phỏng I/O
    # thật — đó là lúc coroutine khác chạy và phải nhìn thấy con số đã tăng.
    import asyncio

    hosts = [_host("a", [_model("m1")]), _host("b", [_model("m1")])]
    reg = StaticHostRegistry(hosts)
    seen: list[str] = []

    async def one_request():
        host = await reg.pick("m1")
        async with reg.lease(host):
            await asyncio.sleep(0)
            seen.append(host.name)

    await asyncio.gather(*(one_request() for _ in range(20)))

    assert set(seen) == {"a", "b"}, f"dồn hết vào một host: {seen}"
    assert abs(seen.count("a") - seen.count("b")) <= 2, f"lệch quá nhiều: {seen}"
    assert all(h.inflight == 0 for h in hosts)
