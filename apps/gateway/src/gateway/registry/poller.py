import asyncio

import httpx
from vypq_contracts.hosting import ModelsResponse
from vypq_core.logging import get_logger

from gateway.db.repo import HostRepo
from gateway.settings import GatewaySettings

log = get_logger(__name__)


class HostPoller:
    """Hỏi ra từng máy GPU xem nó còn sống và đang phục vụ model nào.

    Chiều gọi là RA, không phải host tự đăng ký về: máy ứng dụng cũng sau NAT,
    còn ngrok chỉ mở một chiều vào máy GPU.
    """

    def __init__(self, session_factory, settings: GatewaySettings) -> None:
        self._factory = session_factory
        self._settings = settings

    async def poll_once(self) -> int:
        async with self._factory() as session:
            hosts = await HostRepo(session).list_all()
        if not hosts:
            return 0
        # Poll song song: một máy treo 30s không được chặn những máy khác.
        await asyncio.gather(*(self._poll_host(h.name, h.url) for h in hosts))
        return len(hosts)

    async def _poll_host(self, name: str, url: str) -> None:
        async with self._factory() as session:
            repo = HostRepo(session)
            token = await repo.token_for(name)
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            try:
                async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                    response = await client.get(f"{url.rstrip('/')}/v1/models")
                if response.status_code >= 400:
                    raise RuntimeError(f"trả {response.status_code}")
                models = ModelsResponse.model_validate(response.json()).models
            except Exception as exc:
                # Mọi lỗi đều chỉ hạ đúng một host. Một máy thuê chết không được
                # kéo theo vòng poll của những máy còn lại.
                log.warning("host_poll_failed", host=name, error=str(exc))
                await repo.mark_polled(name, healthy=False, models=[], error=str(exc))
                return
            await repo.mark_polled(name, healthy=True, models=models, error=None)

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # noqa: BLE001 - vòng nền không được chết
                log.exception("poll_loop_error", error=str(exc))
            await asyncio.sleep(self._settings.poll_interval_s)
