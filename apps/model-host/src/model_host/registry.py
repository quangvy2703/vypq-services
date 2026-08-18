import time
from collections.abc import Callable

from vypq_contracts.common import ErrorCode
from vypq_contracts.hosting import ModelInfo
from vypq_core.errors import ServiceError
from vypq_core.logging import get_logger

from model_host.runners.base import ModelRunner
from model_host.spec import HostConfig, ModelSpec

log = get_logger(__name__)


class _Loaded:
    __slots__ = ("runner", "spec", "last_used")

    def __init__(self, runner: ModelRunner, spec: ModelSpec, last_used: int) -> None:
        self.runner = runner
        self.spec = spec
        self.last_used = last_used


class ModelRegistry:
    """Lazy load, evict LRU theo vram_budget_mb. Model pinned không bao giờ bị evict.

    Model bị đánh dấu unavailable (load lỗi) sẽ ở trạng thái đó vĩnh viễn cho tới
    khi tiến trình khởi động lại — đây là chủ đích, không phải quên retry.
    """

    def __init__(self, config: HostConfig, runners: dict[str, Callable[[], ModelRunner]]) -> None:
        self._config = config
        self._runners = runners
        self._specs = {spec.id: spec for spec in config.models}
        self._loaded: dict[str, _Loaded] = {}
        self._unavailable: set[str] = set()
        self._tick = 0

    @property
    def host_name(self) -> str:
        return self._config.host_name

    def infos(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id=s.id, task=s.task, kind=s.kind, runner=s.runner, vram_mb=s.vram_mb,
                base=s.base, trained_on=s.trained_on,
                loaded=s.id in self._loaded,
                available=s.id not in self._unavailable,
            )
            for s in self._config.models
        ]

    def acquire(self, model_id: str) -> tuple[ModelRunner, ModelSpec, int]:
        spec = self._specs.get(model_id)
        if spec is None:
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE, f"không có model '{model_id}' trên host này", 404
            )
        if model_id in self._unavailable:
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE, f"model '{model_id}' đang không dùng được", 503
            )

        self._tick += 1
        if entry := self._loaded.get(model_id):
            entry.last_used = self._tick
            return entry.runner, entry.spec, 0

        self._make_room(spec)
        factory = self._runners.get(spec.runner)
        if factory is None:
            raise ServiceError(
                ErrorCode.INTERNAL, f"không biết runner '{spec.runner}'", 500
            )
        started = time.monotonic()
        runner = factory()
        try:
            runner.load(spec)
        except Exception as exc:
            # Một model hỏng không được làm sập cả host.
            self._unavailable.add(model_id)
            log.error("model_load_failed", model_id=model_id, error=str(exc))
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE, f"không load được '{model_id}': {exc}", 503
            ) from exc
        load_ms = int((time.monotonic() - started) * 1000)
        self._loaded[model_id] = _Loaded(runner, spec, self._tick)
        log.info("model_loaded", model_id=model_id, load_ms=load_ms)
        return runner, spec, load_ms

    def _used_mb(self) -> int:
        return sum(e.spec.vram_mb for e in self._loaded.values())

    def _make_room(self, spec: ModelSpec) -> None:
        budget = self._config.vram_budget_mb
        if spec.vram_mb > budget:
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE,
                f"model '{spec.id}' cần {spec.vram_mb}MB, lớn hơn ngân sách {budget}MB",
                503,
            )
        while self._used_mb() + spec.vram_mb > budget:
            evictable = [e for e in self._loaded.values() if not e.spec.pinned]
            if not evictable:
                raise ServiceError(
                    ErrorCode.MODEL_UNAVAILABLE,
                    f"không đủ VRAM cho '{spec.id}': các model đang giữ đều là pinned",
                    503,
                )
            victim = min(evictable, key=lambda e: e.last_used)
            victim.runner.unload()
            del self._loaded[victim.spec.id]
            log.info("model_evicted", model_id=victim.spec.id)
