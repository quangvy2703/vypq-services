import pytest
from model_host.registry import ModelRegistry
from model_host.runners import RUNNERS
from model_host.spec import HostConfig, ModelSpec
from vypq_contracts.common import ModelKind, Task
from vypq_core.errors import ServiceError


def _spec(mid: str, runner: str) -> ModelSpec:
    return ModelSpec(
        id=mid, task=Task.OCR, kind=ModelKind.OPENSOURCE, runner=runner, vram_mb=100
    )


def test_paddle_runner_is_registered_even_without_the_library():
    # Đăng ký luôn là chủ ý: nhờ vậy lỗi thiếu thư viện đi qua đường cô lập của
    # registry (503 + unavailable) thay vì đường "không biết runner" (500, lặp mãi).
    assert "paddle" in RUNNERS


def test_missing_library_isolates_one_model_and_says_how_to_fix_it():
    try:
        import paddleocr  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("máy này có paddleocr, đường lỗi không tái hiện được")

    config = HostConfig(
        host_name="gpu-1",
        vram_budget_mb=5000,
        models=[_spec("p", "paddle"), _spec("f", "fake")],
    )
    registry = ModelRegistry(config, runners=RUNNERS)

    with pytest.raises(ServiceError) as exc:
        registry.acquire("p")
    assert exc.value.http_status == 503
    assert "uv sync --extra gpu" in exc.value.message   # phải nói cách sửa

    registry.acquire("f")                                # model khác không bị vạ lây
    assert {i.id: i.available for i in registry.infos()} == {"p": False, "f": True}
