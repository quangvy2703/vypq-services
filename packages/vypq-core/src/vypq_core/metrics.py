from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

EVENTS_PAUSED = Counter(
    "vypq_events_consumer_paused_total",
    "Số lần consumer dừng vì sự cố hạ tầng",
    ["topic"],
)
EVENTS_DEAD_LETTERED = Counter(
    "vypq_events_dead_lettered_total",
    "Số message bị đẩy vào dead-letter",
    ["topic"],
)
DLQ_PUBLISH_FAILED = Counter(
    "vypq_events_dlq_publish_failed_total",
    "Số lần ghi vào DLQ thất bại — partition đang kẹt",
    ["topic"],
)


def build_metrics_router() -> APIRouter:
    router = APIRouter()

    @router.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router
