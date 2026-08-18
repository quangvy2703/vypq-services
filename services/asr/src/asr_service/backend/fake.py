from vypq_contracts.asr import RawAsrOutput


class FakeAsrBackend:
    """Backend không cần mạng, không cần GPU. Lý do chính khiến backend là interface."""

    def __init__(
        self, output: RawAsrOutput | None = None, error: Exception | None = None
    ) -> None:
        self._output = output or RawAsrOutput()
        self._error = error
        self.calls: list[tuple[bytes, str]] = []

    async def infer(self, image: bytes, model_id: str) -> RawAsrOutput:
        self.calls.append((image, model_id))
        if self._error is not None:
            raise self._error
        return self._output
