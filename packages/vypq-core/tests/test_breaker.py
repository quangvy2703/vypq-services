from vypq_core.breaker import CircuitBreaker, CircuitState


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(clock: FakeClock) -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=3, recovery_timeout_s=30.0, clock=clock)


def test_starts_closed_and_allows():
    b = _breaker(FakeClock())
    assert b.state is CircuitState.CLOSED
    assert b.allow() is True


def test_opens_after_threshold_consecutive_failures():
    b = _breaker(FakeClock())
    for _ in range(3):
        b.record_failure()
    assert b.state is CircuitState.OPEN
    assert b.allow() is False


def test_success_resets_failure_count():
    b = _breaker(FakeClock())
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.state is CircuitState.CLOSED


def test_moves_to_half_open_after_recovery_timeout():
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    assert b.allow() is False
    clock.advance(30.0)
    assert b.allow() is True
    assert b.state is CircuitState.HALF_OPEN


def test_half_open_success_closes_circuit():
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    clock.advance(31.0)
    b.allow()
    b.record_success()
    assert b.state is CircuitState.CLOSED
    assert b.allow() is True


def test_half_open_failure_reopens_immediately():
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    clock.advance(31.0)
    b.allow()
    b.record_failure()
    assert b.state is CircuitState.OPEN
    assert b.allow() is False


def test_stale_probe_does_not_wedge_the_circuit_forever():
    # Caller nhận probe rồi biến mất, không record_success cũng không record_failure.
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    clock.advance(31.0)
    assert b.allow() is True

    clock.advance(31.0)
    assert b.allow() is False                 # probe treo bị thu hồi, circuit mở lại
    assert b.state is CircuitState.OPEN

    clock.advance(31.0)
    assert b.allow() is True                  # tự hồi phục, cấp probe mới


def test_half_open_allows_only_one_probe():
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    clock.advance(31.0)
    assert b.allow() is True
    assert b.allow() is False
