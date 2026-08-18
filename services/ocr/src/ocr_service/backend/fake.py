from vypq_contracts.ocr import RawOcrOutput


class FakeOcrBackend:
    """Backend không cần mạng, không cần GPU. Lý do chính khiến backend là interface."""

    def __init__(
        self, output: RawOcrOutput | None = None, error: Exception | None = None
    ) -> None:
        self._output = output or RawOcrOutput()
        self._error = error
        self.calls: list[tuple[bytes, str]] = []

    async def infer(self, image: bytes, model_id: str) -> RawOcrOutput:
        self.calls.append((image, model_id))
        if self._error is not None:
            raise self._error
        return self._output
