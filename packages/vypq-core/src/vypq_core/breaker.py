import time
from collections.abc import Callable
from enum import StrEnum

from vypq_contracts.common import ErrorCode

from vypq_core.errors import ServiceError


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(ServiceError):
    def __init__(self, target: str) -> None:
        super().__init__(
            ErrorCode.CIRCUIT_OPEN,
            f"circuit đang mở cho {target}",
            http_status=503,
        )


class CircuitBreaker:
    """Mở sau N lỗi liên tiếp, half-open sau T giây, đóng lại khi probe thành công."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = failure_threshold
        self._recovery = recovery_timeout_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_started_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return CircuitState.CLOSED
        if self._probe_started_at is not None:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        now = self._clock()
        if self._probe_started_at is not None:
            if now - self._probe_started_at < self._recovery:
                # Half-open chỉ cho đúng một request thăm dò đi qua.
                return False
            # Probe treo: caller đi ra mà không bao giờ báo lại (exception thoát ở
            # nhánh không record, task bị cancel, tiến trình chết giữa chừng).
            # Không có mốc thời gian này thì breaker kẹt HALF_OPEN vĩnh viễn và
            # chặn mọi request về sau, im lặng, không cách nào tự hồi phục.
            self._probe_started_at = None
            self._opened_at = now
            return False
        if now - self._opened_at >= self._recovery:
            self._probe_started_at = now
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._probe_started_at = None

    def record_failure(self) -> None:
        if self._probe_started_at is not None:
            # Probe hỏng → mở lại ngay, tính lại thời gian chờ.
            self._probe_started_at = None
            self._opened_at = self._clock()
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()

    def is_open(self) -> bool:
        """True cả khi OPEN lẫn HALF_OPEN — dùng để báo /ready degraded.

        Đừng dùng hàm này để chặn vòng lặp: HALF_OPEN chính là lúc phải cho một
        request đi qua. Nơi nào cần quyết định gửi hay không thì gọi `allow()`.
        """
        return self.state is not CircuitState.CLOSED
