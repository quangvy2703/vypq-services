from datetime import UTC, datetime

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from vypq_contracts.gateway import HostRegistration, HostState
from vypq_contracts.hosting import ModelInfo

from gateway.db.models import Host


def _to_state(row: Host) -> HostState:
    return HostState(
        name=row.name,
        url=row.url,
        healthy=row.healthy,
        models=[ModelInfo.model_validate(m) for m in (row.models_json or [])],
        last_seen_at=row.last_seen_at,
        last_error=row.last_error,
    )


class HostRepo:
    """Nơi duy nhất chạm bảng `hosts`."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, reg: HostRegistration) -> HostState:
        row = await self._load_and_apply(reg)
        try:
            await self._s.commit()
        except IntegrityError:
            # Hai box GPU đăng ký cùng một tên gần như đồng thời (ví dụ một
            # script thuê rồi đăng ký nhiều máy liên tiếp) là vận hành bình
            # thường, không phải lỗi. Đoạn read-modify-write ở trên có khe hở
            # giữa SELECT và INSERT: cả hai request cùng thấy "chưa tồn tại"
            # rồi cùng INSERT, bên thua thua cuộc đua trên khoá chính và nhận
            # IntegrityError. Rollback rồi đọc lại — lần này sẽ thấy row mà
            # bên thắng vừa chèn — và UPDATE nó thay vì INSERT lần nữa. Đăng
            # ký đến sau thắng, y hệt như đăng ký lại tuần tự.
            await self._s.rollback()
            row = await self._load_and_apply(reg)
            await self._s.commit()
        return _to_state(row)

    async def _load_and_apply(self, reg: HostRegistration) -> Host:
        row = await self._s.get(Host, reg.name)
        if row is None:
            row = Host(name=reg.name, registered_at=datetime.now(UTC))
            self._s.add(row)
        elif row.url != reg.url:
            # URL mới nghĩa là máy khác. Giữ lại healthy của máy cũ sẽ khiến
            # gateway định tuyến vào một tunnel chưa ai kiểm chứng lần nào.
            row.healthy = False
            row.models_json = []
            row.last_seen_at = None
            row.last_error = None
        row.url = reg.url
        row.token = reg.token
        return row

    async def get(self, name: str) -> HostState | None:
        row = await self._s.get(Host, name)
        return None if row is None else _to_state(row)

    async def list_all(self) -> list[HostState]:
        rows = (await self._s.execute(select(Host).order_by(Host.name))).scalars().all()
        return [_to_state(r) for r in rows]

    async def delete(self, name: str) -> bool:
        result = await self._s.execute(sql_delete(Host).where(Host.name == name))
        await self._s.commit()
        return result.rowcount > 0

    async def mark_polled(
        self, name: str, *, healthy: bool, models: list[ModelInfo], error: str | None
    ) -> None:
        row = await self._s.get(Host, name)
        if row is None:
            return
        row.healthy = healthy
        row.last_error = error
        if healthy:
            row.models_json = [m.model_dump(mode="json") for m in models]
            row.last_seen_at = datetime.now(UTC)
        await self._s.commit()

    async def token_for(self, name: str) -> str | None:
        row = await self._s.get(Host, name)
        return None if row is None else row.token
