import pytest
from gateway.dispatcher import Dispatcher
from gateway.registry.services import ServiceEntry, ServiceRegistry
from vypq_contracts.common import HealthStatus, Task
from vypq_contracts.gateway import InvokeMode, InvokeRequest, ServiceInfo, ServiceState
from vypq_core.errors import ServiceError


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple] = []

    async def publish(self, topic, envelope, key=None):
        self.published.append((topic, envelope, key))


def _registry(status=HealthStatus.OK) -> ServiceRegistry:
    reg = ServiceRegistry([ServiceEntry(name="ocr", base_url="http://ocr:8001")])
    reg._states["ocr"] = ServiceState(
        name="ocr", info=ServiceInfo(
            name="ocr", task=Task.OCR, capability_input="image",
            capability_output="text_boxes", version="0.1.0", invoke_path="/v1/ocr",
        ),
        base_url="http://ocr:8001",
        status=status,
    )
    return reg


async def test_dispatch_publishes_to_the_task_request_topic():
    producer = FakeProducer()
    await Dispatcher(_registry(), producer).dispatch(
        InvokeRequest(service="ocr", mode=InvokeMode.ASYNC, input_uri="s3://b/a.jpg"),
        "trace-1",
    )
    topic, envelope, key = producer.published[0]
    assert topic == "infer.ocr.requests"
    assert key == "trace-1"
    assert envelope.trace_id == "trace-1"
    assert envelope.payload.input_uri == "s3://b/a.jpg"


async def test_model_version_is_carried_into_the_event():
    producer = FakeProducer()
    await Dispatcher(_registry(), producer).dispatch(
        InvokeRequest(
            service="ocr", mode=InvokeMode.ASYNC,
            input_uri="s3://b/a.jpg", model_version="vietocr-ft",
        ),
        "trace-1",
    )
    assert producer.published[0][1].payload.model_version == "vietocr-ft"


async def test_topic_comes_from_the_service_task_not_its_name():
    # Hai service cùng task đọc chung topic — đó là cơ chế shadow-run, cố ý.
    producer = FakeProducer()
    reg = _registry()
    reg._states["ocr"].info.name = "ocr-viet-tay"
    await Dispatcher(reg, producer).dispatch(
        InvokeRequest(service="ocr", mode=InvokeMode.ASYNC, input_uri="s3://b/a.jpg"),
        "trace-1",
    )
    assert producer.published[0][0] == "infer.ocr.requests"


async def test_unknown_service_is_refused_without_publishing():
    producer = FakeProducer()
    with pytest.raises(ServiceError) as exc:
        await Dispatcher(_registry(), producer).dispatch(
            InvokeRequest(service="khong-co", mode=InvokeMode.ASYNC, input_uri="s3://a"),
            "trace-1",
        )
    assert exc.value.http_status == 404
    assert producer.published == []


async def test_down_service_still_accepts_async_work():
    # Khác đường sync: message nằm trong topic chờ service sống lại, không mất.
    # Từ chối ở đây là vứt việc đi vì một sự cố tạm thời.
    producer = FakeProducer()
    await Dispatcher(_registry(HealthStatus.DOWN), producer).dispatch(
        InvokeRequest(service="ocr", mode=InvokeMode.ASYNC, input_uri="s3://b/a.jpg"),
        "trace-1",
    )
    assert len(producer.published) == 1


async def test_missing_input_uri_is_refused():
    producer = FakeProducer()
    with pytest.raises(ServiceError):
        await Dispatcher(_registry(), producer).dispatch(
            InvokeRequest(service="ocr", mode=InvokeMode.ASYNC), "trace-1"
        )
    assert producer.published == []
