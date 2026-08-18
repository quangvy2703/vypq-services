from typing import Protocol

from vypq_contracts.__TASK__ import __RAWOUT__


class __BACKEND__(Protocol):
    async def infer(self, image: bytes, model_id: str) -> __RAWOUT__: ...
