from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Host(Base):
    """Máy GPU thuê. Tên là khoá chính vì đó là danh tính người vận hành đặt;
    URL đổi mỗi lần thuê lại nên không dùng làm khoá được."""

    __tablename__ = "hosts"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(512))
    token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    healthy: Mapped[bool] = mapped_column(Boolean, default=False)
    # JSON chứ không JSONB: test mặc định chạy trên SQLite, không có Docker.
    models_json: Mapped[list] = mapped_column(JSON, default=list)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Run(Base):
    """Một lần chạy inference. Khoá duy nhất (trace_id, model_version) chống
    xử lý trùng do Kafka giao ít nhất một lần, đồng thời cho phép shadow-run:
    cùng một trace_id nhưng nhiều model version là nhiều dòng hợp lệ."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    # Chuỗi rỗng chứ không NULL: SQL coi mọi NULL là khác nhau nên khoá duy nhất
    # sẽ không chặn được trùng ở dòng chưa biết model version.
    model_version: Mapped[str] = mapped_column(String(128), default="")
    mode: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(8), index=True)
    input_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        UniqueConstraint("trace_id", "model_version", name="uq_run_trace_model"),
    )
