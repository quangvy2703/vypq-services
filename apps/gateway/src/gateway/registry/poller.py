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
        # return_exceptions=True là bảo đảm CẤU TRÚC: _poll_host hỏng ở bất kỳ
        # đâu — kể cả lúc ghi DB — cũng chỉ hạ đúng host đó. Không có nó thì một
        # exception lọt ra sẽ giết cả vòng poll và toàn bộ registry đứng im, âm
        # thầm, vì run() bắt lỗi ở tầng cao hơn.
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                *(self._poll_host(client, h.name, h.url) for h in hosts),
                return_exceptions=True,
            )
        for host, result in zip(hosts, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                # Huỷ là tín hiệu tắt máy, không phải lỗi của host — phải bay tiếp,
                # nếu không lifespan sẽ treo khi shutdown.
                raise result
            if isinstance(result, BaseException):
                log.exception("host_poll_crashed", host=host.name, error=str(result))
        return len(hosts)

    async def _poll_host(self, client: httpx.AsyncClient, name: str, url: str) -> None:
        try:
            async with self._factory() as session:
                repo = HostRepo(session)
                token = await repo.token_for(name)
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                try:
                    response = await client.get(f"{url.rstrip('/')}/v1/models", headers=headers)
                    if response.status_code >= 400:
                        raise RuntimeError(f"trả {response.status_code}")
                    models = ModelsResponse.model_validate(response.json()).models
                except Exception as exc:
                    # Mọi lỗi HTTP/parse đều chỉ hạ đúng một host. Một máy thuê
                    # chết không được kéo theo vòng poll của những máy còn lại.
                    log.warning("host_poll_failed", host=name, error=str(exc))
                    await repo.mark_polled(name, healthy=False, models=[], error=str(exc))
                    return
                await repo.mark_polled(name, healthy=True, models=models, error=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Ghi DB thất bại (token_for hoặc mark_polled) thì không còn gì để
            # ghi nữa — chỉ log kèm host để gather ở trên không phải đoán.
            log.warning("host_poll_db_failed", host=name, error=str(exc))
            return

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # noqa: BLE001 - vòng nền không được chết
                log.exception("poll_loop_error", error=str(exc))
            await asyncio.sleep(self._settings.poll_interval_s)
