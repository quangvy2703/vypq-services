import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import HostRegistration, HostState, InvokeMode, RunRecord, RunStatus
from vypq_contracts.hosting import ModelInfo
from vypq_core.errors import ServiceError
from vypq_core.host_registry import HostRef

from gateway.db.models import Host, Run


def _is_fresh(last_seen_at: datetime | None, *, now: datetime, ttl_s: float) -> bool:
    # Dùng chung giữa list_all_states() và list_all_refs() để hai endpoint
    # KHÔNG THỂ lệch nhau về định nghĩa "tươi" — trùng lặp công thức này ở hai
    # chỗ là đúng loại lỗi khiến dashboard và routing bất đồng với nhau.
    if last_seen_at is None:
        return False
    elapsed = (now - last_seen_at).total_seconds()
    # Chặn cả hai đầu. Hiệu ÂM nghĩa là đồng hồ lệch (nhiều replica gateway,
    # hoặc NTP trôi), và `<= ttl` một mình sẽ cho qua vô điều kiện — host đó
    # khoẻ vĩnh viễn, đúng ngược lại mục đích của việc tính lại độ tươi ở đây.
    return 0 <= elapsed <= ttl_s


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

    async def list_all_states(self, *, now: datetime, ttl_s: float) -> list[HostState]:
        """Như list_all(), nhưng tính lại độ tươi giống list_all_refs() (xem
        docstring ở đó — cùng công thức, cùng chặn lệch đồng hồ).

        `GET /v1/hosts` (dashboard) trước đây gọi list_all() và trả thẳng cờ
        `healthy` đã lưu trong DB — cờ đó đóng băng ở lần poll cuối. Nếu poller
        treo, dashboard báo `healthy=True` cho một host mà MỌI service qua
        `/v1/discovery/hosts` đã coi là chết (route vẫn an toàn vì nó luôn đi
        qua list_all_refs()), nhưng dashboard nói dối. Kế hoạch tiếp theo dựng
        trên đúng con số này, nên hai endpoint phải đồng ý với nhau — không
        đọc token, khác list_all_refs() ở đúng chỗ đó.
        """
        rows = (await self._s.execute(select(Host).order_by(Host.name))).scalars().all()
        return [
            HostState(
                name=row.name,
                url=row.url,
                healthy=row.healthy and _is_fresh(row.last_seen_at, now=now, ttl_s=ttl_s),
                models=[ModelInfo.model_validate(m) for m in (row.models_json or [])],
                last_seen_at=row.last_seen_at,
                last_error=row.last_error,
            )
            for row in rows
        ]

    async def list_all_refs(self, *, now: datetime, ttl_s: float) -> list[HostRef]:
        """Đọc trạng thái và token trong CÙNG MỘT truy vấn, cùng một snapshot.

        `/v1/discovery/hosts` cần cả trạng thái (healthy, models) lẫn token, và
        trước đây lấy hai thứ đó bằng hai lượt đọc riêng (list_all() rồi
        token_for() cho từng host). Giữa hai lượt đọc đó một host có thể bị
        đăng ký lại — thuê máy theo giờ là chuyện bình thường, không phải lỗi
        — và kết quả sẽ ghép URL CŨ với token MỚI, cùng cờ healthy=True sót lại
        trong khi upsert() đã tự đặt lại về False vì URL đổi (upsert chủ đích
        làm vậy để không định tuyến vào một tunnel chưa ai kiểm chứng). Đọc một
        lần duy nhất, từ một snapshot, loại bỏ khả năng ghép lệch đó — đồng thời
        gộp N truy vấn (một cho state, N cho token) thành một.
        """
        rows = (await self._s.execute(select(Host).order_by(Host.name))).scalars().all()
        return [
            HostRef(
                name=row.name,
                url=row.url,
                token=row.token,
                models=[ModelInfo.model_validate(m) for m in (row.models_json or [])],
                healthy=row.healthy and _is_fresh(row.last_seen_at, now=now, ttl_s=ttl_s),
            )
            for row in rows
        ]

    async def delete(self, name: str) -> bool:
        # session.execute() is typed to return the generic Result, but for a
        # Core DML construct like delete() it always returns a CursorResult
        # at runtime (CursorResult subclasses Result) — that's what carries
        # rowcount. Narrowing here reflects that documented SQLAlchemy
        # behaviour rather than papering over an actual type mismatch.
        result = cast(
            CursorResult,
            await self._s.execute(sql_delete(Host).where(Host.name == name)),
        )
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


def _to_run(row: Run) -> RunRecord:
    return RunRecord(
        id=row.id, trace_id=row.trace_id, service=row.service,
        model_version=row.model_version or None, mode=InvokeMode(row.mode),
        status=RunStatus(row.status), input_uri=row.input_uri,
        output=row.output_json, latency_ms=row.latency_ms, error=row.error,
        created_at=row.created_at,
    )


class RunRepo:
    """Nơi duy nhất chạm bảng `runs`."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def record(
        self,
        *,
        trace_id: str,
        service: str,
        model_version: str | None,
        mode: InvokeMode,
        status: RunStatus,
        input_uri: str | None,
        output: dict | None,
        latency_ms: int | None,
        error: str | None,
        reject_duplicate_trace: bool = False,
    ) -> RunRecord:
        """Ghi một dòng `runs`, dedup theo (trace_id, model_version).

        `reject_duplicate_trace` phân biệt HAI nguồn gốc khác nhau của
        trace_id, thứ dedup-trả-về-bản-cũ chỉ đúng với MỘT trong hai:

        - False (mặc định, đường async/result_consumer): trace_id do CHÍNH
          GATEWAY sinh ra lúc dispatch rồi Kafka giao lại. Kafka giao ít nhất
          một lần nên bản trùng ở đây LÀ CÙNG MỘT kết quả tới hai lần — trả về
          bản cũ là đúng.
        - True (đường sync qua SyncProxy): gateway giờ tôn trọng x-trace-id do
          CALLER gửi lên. Hai request khác nhau tình cờ/chủ đích trùng header
          không phải là "cùng một kết quả tới hai lần" — nếu vẫn dedup-trả-về-
          bản-cũ thì caller thứ hai ÂM THẦM NHẬN KẾT QUẢ CỦA CALLER THỨ NHẤT
          (GPU đã chạy xong request của họ, kết quả bị vứt). Với client-chọn
          trace_id, trùng là lỗi CỦA CLIENT, không phải bản sao lành tính —
          phải từ chối bằng ServiceError 409, không được trả nhầm dữ liệu.
        """
        key = model_version or ""
        existing = (
            await self._s.execute(
                select(Run).where(Run.trace_id == trace_id, Run.model_version == key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if reject_duplicate_trace:
                raise ServiceError(
                    ErrorCode.BAD_INPUT,
                    f"trace_id '{trace_id}' đã được dùng cho model_version '{key}'",
                    409,
                )
            # Đã ghi rồi: Kafka giao ít nhất một lần nên bản sao là bình thường,
            # không phải lỗi. Giữ bản đầu, không đè.
            return _to_run(existing)

        row = Run(
            id=uuid.uuid4().hex, trace_id=trace_id, service=service,
            model_version=key, mode=mode.value, status=status.value,
            input_uri=input_uri, output_json=output, latency_ms=latency_ms,
            error=error, created_at=datetime.now(UTC),
        )
        self._s.add(row)
        try:
            await self._s.commit()
        except IntegrityError as exc:
            # Thua cuộc đua ghi: một tiến trình khác vừa ghi đúng cặp
            # (trace_id, model_version) này.
            await self._s.rollback()
            existing = (
                await self._s.execute(
                    select(Run).where(Run.trace_id == trace_id, Run.model_version == key)
                )
            ).scalar_one()
            if reject_duplicate_trace:
                raise ServiceError(
                    ErrorCode.BAD_INPUT,
                    f"trace_id '{trace_id}' đã được dùng cho model_version '{key}'",
                    409,
                ) from exc
            # Bản sao Kafka lành tính, không phải lỗi — đọc lại bản của bên
            # thắng và trả về. Để exception bay tiếp thì consumer coi là dữ
            # liệu hỏng và dead-letter một KẾT QUẢ INFERENCE ĐÃ CHẠY XONG.
            return _to_run(existing)
        return _to_run(row)

    async def get(self, run_id: str) -> RunRecord | None:
        row = await self._s.get(Run, run_id)
        return None if row is None else _to_run(row)

    async def list_runs(
        self,
        *,
        trace_id: str | None = None,
        service: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RunRecord], int]:
        filters = []
        if trace_id is not None:
            # Đường async chỉ trả về trace_id, không trả run_id (kết quả có thể
            # về từ nhiều model version). Thiếu bộ lọc này thì người gọi async
            # không có cách nào tìm lại kết quả của chính mình.
            filters.append(Run.trace_id == trace_id)
        if service is not None:
            filters.append(Run.service == service)
        if status is not None:
            filters.append(Run.status == status.value)

        total = (
            await self._s.execute(select(func.count()).select_from(Run).where(*filters))
        ).scalar_one()
        rows = (
            await self._s.execute(
                select(Run).where(*filters)
                .order_by(Run.created_at.desc(), Run.id.desc())
                .limit(limit).offset(offset)
            )
        ).scalars().all()
        return [_to_run(r) for r in rows], total
