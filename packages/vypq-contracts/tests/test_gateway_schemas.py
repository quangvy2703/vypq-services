from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from vypq_contracts.common import HealthStatus, ModelKind, Task
from vypq_contracts.gateway import (
    HostRegistration,
    HostsResponse,
    HostState,
    InvokeMode,
    InvokeRequest,
    InvokeResponse,
    RunRecord,
    RunsResponse,
    RunStatus,
    ServiceInfo,
    ServiceState,
)
from vypq_contracts.hosting import ModelInfo


def _model() -> ModelInfo:
    return ModelInfo(id="m1", task=Task.OCR, kind=ModelKind.OPENSOURCE, runner="paddle")


def test_host_registration_requires_name_and_url():
    reg = HostRegistration(name="gpu-1", url="https://a.ngrok.app", token="t")
    assert reg.token == "t"
    with pytest.raises(ValidationError):
        HostRegistration(name="gpu-1")


def test_host_registration_token_is_optional():
    assert HostRegistration(name="gpu-1", url="http://h:9000").token is None


def test_host_state_defaults_to_unhealthy_until_polled():
    # Máy vừa đăng ký chưa được poll lần nào: chưa biết nó sống hay chết, và
    # "chưa biết" phải nghiêng về KHÔNG định tuyến vào, không phải ngược lại.
    state = HostState(name="gpu-1", url="http://h:9000")
    assert state.healthy is False
    assert state.models == []
    assert state.last_seen_at is None


def test_hosts_response_roundtrip():
    resp = HostsResponse(
        hosts=[
            HostState(
                name="gpu-1",
                url="http://h:9000",
                healthy=True,
                models=[_model()],
                last_seen_at=datetime.now(UTC),
            )
        ]
    )
    parsed = HostsResponse.model_validate_json(resp.model_dump_json())
    assert parsed.hosts[0].models[0].id == "m1"


def test_host_state_never_carries_the_token():
    # HostsResponse đi tới service qua mạng nội bộ, nhưng token của máy GPU là
    # bí mật của gateway — nó phải được cấp riêng, không phát kèm danh sách.
    assert "token" not in HostState.model_fields


def test_service_info_roundtrip():
    info = ServiceInfo(
        name="ocr", task=Task.OCR, capability_input="image",
        capability_output="text_boxes", version="0.1.0", invoke_path="/v1/ocr",
        default_model="paddleocr-v4-vi",
    )
    assert ServiceInfo.model_validate_json(info.model_dump_json()) == info


def test_service_info_requires_invoke_path():
    # Gateway POST vào đây; không có thì nó phải đoán, và đoán là gọi sai đường.
    with pytest.raises(ValidationError):
        ServiceInfo(
            name="ocr", task=Task.OCR, capability_input="image",
            capability_output="text_boxes", version="0.1.0",
        )


def test_service_state_carries_health():
    state = ServiceState(
        info=ServiceInfo(
            name="ocr", task=Task.OCR, capability_input="image",
            capability_output="text_boxes", version="0.1.0", invoke_path="/v1/ocr",
        ),
        base_url="http://ocr:8001",
        status=HealthStatus.DEGRADED,
    )
    assert state.status is HealthStatus.DEGRADED
    assert state.info.default_model is None


def test_service_state_info_defaults_to_none():
    # Chưa từng poll thành công thì không có ServiceInfo thật để gắn vào —
    # info phải construct được mà không truyền, và mặc định là None chứ
    # không phải một giá trị đoán (vd hardcode Task.OCR).
    state = ServiceState(base_url="http://ocr:8001")
    assert state.info is None


def test_invoke_defaults_to_sync():
    req = InvokeRequest(service="ocr")
    assert req.mode is InvokeMode.SYNC
    assert req.model_version is None


def test_invoke_mode_is_a_string_enum():
    assert InvokeMode.ASYNC == "async"
    assert f"{InvokeMode.ASYNC}" == "async"


def test_empty_model_version_reads_back_as_none():
    # Tầng DB lưu "" thay cho NULL để khoá duy nhất còn hiệu lực. Đọc lên phải
    # về None, nếu không mọi chỗ kiểm `is None` sẽ trượt đúng những dòng đó.
    run = RunRecord(
        id="r1", trace_id="t1", service="ocr", model_version="",
        mode=InvokeMode.ASYNC, status=RunStatus.PENDING, created_at=datetime.now(UTC),
    )
    assert run.model_version is None


def test_async_invoke_response_has_no_run_id_yet():
    # Đường async chưa tạo dòng runs: kết quả có thể về từ nhiều model version,
    # mỗi cái một dòng. Người gọi tra lại bằng trace_id.
    resp = InvokeResponse(trace_id="t1", mode=InvokeMode.ASYNC)
    assert resp.run_id is None
    assert resp.result is None


def test_sync_invoke_response_carries_run_id_and_result():
    resp = InvokeResponse(
        trace_id="t1", mode=InvokeMode.SYNC, run_id="r1", result={"full_text": "a"}
    )
    assert resp.run_id == "r1"
    assert resp.result["full_text"] == "a"


def test_run_status_is_a_string_enum():
    assert RunStatus.FAILED == "failed"
    assert f"{RunStatus.FAILED}" == "failed"


def test_runs_response_defaults_to_empty():
    assert RunsResponse().runs == []
    assert RunsResponse().total == 0


def test_run_record_roundtrip():
    run = RunRecord(
        id="r1", trace_id="t1", service="ocr", model_version="m1",
        mode=InvokeMode.SYNC, status=RunStatus.OK, input_uri="s3://b/a.jpg",
        output={"full_text": "xin chào"}, latency_ms=42, created_at=datetime.now(UTC),
    )
    parsed = RunRecord.model_validate_json(run.model_dump_json())
    assert parsed.output["full_text"] == "xin chào"
    assert parsed.error is None
