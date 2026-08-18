import uuid
from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class EventEnvelope(BaseModel, Generic[T]):  # noqa: UP046 — classic TypeVar/Generic kept intentionally (task-7 spec).
    event_id: str
    event_type: str
    trace_id: str
    occurred_at: datetime
    payload: T

    @classmethod
    def new(cls, event_type: str, payload: T, trace_id: str | None = None):
        return cls(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            trace_id=trace_id or uuid.uuid4().hex,
            occurred_at=datetime.now(UTC),
            payload=payload,
        )


class RawEnvelope(BaseModel):
    """Envelope chưa biết kiểu payload — dùng khi đẩy vào DLQ."""

    event_id: str
    event_type: str
    trace_id: str
    occurred_at: datetime
    payload: dict = Field(default_factory=dict)
