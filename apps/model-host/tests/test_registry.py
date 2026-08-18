import pytest
from model_host.registry import ModelRegistry
from model_host.runners.fake import FakeOcrRunner
from model_host.spec import HostConfig, ModelSpec
from vypq_contracts.common import ModelKind, Task
from vypq_core.errors import ServiceError


def _spec(mid: str, vram: int, pinned: bool = False) -> ModelSpec:
    return ModelSpec(
        id=mid, task=Task.OCR, kind=ModelKind.OPENSOURCE, runner="fake",
        vram_mb=vram, pinned=pinned,
    )


def _registry(specs: list[ModelSpec], budget: int) -> ModelRegistry:
    config = HostConfig(host_name="gpu-1", vram_budget_mb=budget, models=specs)
    return ModelRegistry(config, runners={"fake": FakeOcrRunner})


def test_models_are_not_loaded_until_acquired():
    reg = _registry([_spec("m1", 1000)], budget=5000)
    assert reg.infos()[0].loaded is False
    reg.acquire("m1")
    assert reg.infos()[0].loaded is True


def test_acquire_returns_same_runner_instance_on_second_call():
    reg = _registry([_spec("m1", 1000)], budget=5000)
    first, _, load_ms_1 = reg.acquire("m1")
    second, _, load_ms_2 = reg.acquire("m1")
    assert first is second
    assert load_ms_2 == 0  # lần thứ hai không tốn thời gian load


def test_evicts_least_recently_used_when_budget_exceeded():
    reg = _registry([_spec("m1", 3000), _spec("m2", 3000)], budget=5000)
    reg.acquire("m1")
    reg.acquire("m2")
    loaded = {i.id: i.loaded for i in reg.infos()}
    assert loaded == {"m1": False, "m2": True}


def test_pinned_model_is_never_evicted():
    reg = _registry([_spec("m1", 3000, pinned=True), _spec("m2", 3000)], budget=5000)
    reg.acquire("m1")
    with pytest.raises(ServiceError) as exc:
        reg.acquire("m2")
    assert "không đủ VRAM" in exc.value.message
    assert reg.infos()[0].loaded is True


def test_recently_used_model_survives_eviction():
    reg = _registry([_spec("m1", 2000), _spec("m2", 2000), _spec("m3", 2000)], budget=5000)
    reg.acquire("m1")
    reg.acquire("m2")
    reg.acquire("m1")   # m1 vừa dùng → m2 mới là cũ nhất
    reg.acquire("m3")
    loaded = {i.id: i.loaded for i in reg.infos()}
    assert loaded == {"m1": True, "m2": False, "m3": True}


def test_model_larger_than_budget_is_rejected_clearly():
    reg = _registry([_spec("m1", 99000)], budget=5000)
    with pytest.raises(ServiceError) as exc:
        reg.acquire("m1")
    assert "lớn hơn ngân sách" in exc.value.message


def test_unknown_model_raises_service_error():
    reg = _registry([_spec("m1", 1000)], budget=5000)
    with pytest.raises(ServiceError):
        reg.acquire("khong-co")


def test_failed_load_marks_model_unavailable_without_killing_host():
    class Broken(FakeOcrRunner):
        def load(self, spec):
            raise RuntimeError("thiếu checkpoint")

    config = HostConfig(
        host_name="gpu-1", vram_budget_mb=5000,
        models=[_spec("m1", 1000), _spec("m2", 1000)],
    )
    config.models[0].runner = "broken"
    reg = ModelRegistry(config, runners={"fake": FakeOcrRunner, "broken": Broken})
    with pytest.raises(ServiceError):
        reg.acquire("m1")
    infos = {i.id: i for i in reg.infos()}
    assert infos["m1"].available is False
    assert infos["m2"].available is True     # model khác không bị ảnh hưởng


def test_unavailable_model_is_not_retried_on_the_next_request():
    attempts = []

    class Broken(FakeOcrRunner):
        def load(self, spec):
            attempts.append(spec.id)
            raise RuntimeError("thiếu checkpoint")

    config = HostConfig(
        host_name="gpu-1", vram_budget_mb=5000, models=[_spec("m1", 1000)]
    )
    config.models[0].runner = "broken"
    reg = ModelRegistry(config, runners={"fake": FakeOcrRunner, "broken": Broken})
    for _ in range(3):
        with pytest.raises(ServiceError):
            reg.acquire("m1")
    assert attempts == ["m1"]     # chỉ thử load đúng một lần
