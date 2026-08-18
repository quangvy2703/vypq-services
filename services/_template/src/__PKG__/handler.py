import time

from vypq_contracts.__TASK__ import __RESP__, __RAWOUT__

from __PKG__.backend.base import __BACKEND__


class __HANDLER__:
    def __init__(self, backend: __BACKEND__, *, default_model: str) -> None:
        self._backend = backend
        self._default_model = default_model

    async def run(self, data: bytes, model_version: str | None, trace_id: str) -> __RESP__:
        model_id = model_version or self._default_model
        started = time.monotonic()
        raw = await self._backend.infer(data, model_id)
        return __RESP__(
            trace_id=trace_id,
            model_version=model_id,
            result=self.to_result(raw),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def to_result(self, raw: __RAWOUT__):
        raise NotImplementedError("service cụ thể phải nối pipeline postprocess của mình")
