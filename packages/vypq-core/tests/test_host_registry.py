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
