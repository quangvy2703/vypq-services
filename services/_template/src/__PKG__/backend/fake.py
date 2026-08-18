from vypq_contracts.__TASK__ import __RAWOUT__


class Fake__BACKEND__:
    """Backend không cần mạng, không cần GPU. Lý do chính khiến backend là interface."""

    def __init__(
        self, output: __RAWOUT__ | None = None, error: Exception | None = None
    ) -> None:
        self._output = output or __RAWOUT__()
        self._error = error
        self.calls: list[tuple[bytes, str]] = []

    async def infer(self, image: bytes, model_id: str) -> __RAWOUT__:
        self.calls.append((image, model_id))
        if self._error is not None:
            raise self._error
        return self._output
