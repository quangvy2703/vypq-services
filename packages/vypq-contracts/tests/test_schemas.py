import pytest
from pydantic import ValidationError

from vypq_contracts.asr import AsrResult, RawAsrOutput, Segment
from vypq_contracts.common import ErrorCode, ErrorResponse, HealthStatus, Task
from vypq_contracts.hosting import InferResponse, InferTiming, ModelInfo
from vypq_contracts.ocr import OcrResult, RawOcrOutput, TextBox


def test_task_values():
    assert Task.OCR.value == "ocr"
    assert Task.ASR.value == "asr"


def test_error_response_roundtrip():
    err = ErrorResponse(code=ErrorCode.BAD_INPUT, message="ảnh hỏng", trace_id="t1")
    assert ErrorResponse.model_validate_json(err.model_dump_json()) == err


def test_health_status_has_degraded():
    assert HealthStatus.DEGRADED.value == "degraded"


def test_textbox_defaults_ignore_false():
    box = TextBox(id=0, polygon=[(0, 0), (10, 0), (10, 5), (0, 5)], text="A")
    assert box.ignore is False
    assert box.confidence is None


def test_textbox_rejects_polygon_with_three_points():
    with pytest.raises(ValidationError):
        TextBox(id=0, polygon=[(0, 0), (10, 0), (10, 5)], text="A")


def test_textbox_accepts_polygon_with_more_than_four_points():
    box = TextBox(
        id=1,
        polygon=[(0, 0), (5, -1), (10, 0), (10, 5), (0, 5)],
        text="cong",
    )
    assert len(box.polygon) == 5


def test_ocr_result_roundtrip():
    result = OcrResult(
        full_text="A\nB",
        boxes=[
            TextBox(id=0, polygon=[(0, 0), (1, 0), (1, 1), (0, 1)], text="A"),
            TextBox(id=1, polygon=[(0, 2), (1, 2), (1, 3), (0, 3)], text="B"),
        ],
    )
    assert OcrResult.model_validate_json(result.model_dump_json()) == result


def test_raw_ocr_output_holds_only_boxes():
    raw = RawOcrOutput(boxes=[])
    assert raw.model_dump() == {"boxes": []}


def test_segment_and_asr_result():
    seg = Segment(start=0.4, end=2.1, text="xin chào", speaker="A")
    res = AsrResult(text="xin chào", segments=[seg])
    assert AsrResult.model_validate_json(res.model_dump_json()) == res


def test_infer_response_discriminates_ocr_output():
    resp = InferResponse(
        model_id="fake-ocr",
        task=Task.OCR,
        output=RawOcrOutput(boxes=[]),
        timing=InferTiming(load_ms=0, infer_ms=12),
    )
    parsed = InferResponse.model_validate_json(resp.model_dump_json())
    assert isinstance(parsed.output, RawOcrOutput)


def test_infer_response_discriminates_asr_output():
    resp = InferResponse(
        model_id="fake-asr",
        task=Task.ASR,
        output=RawAsrOutput(segments=[Segment(start=0.0, end=1.0, text="a")]),
        timing=InferTiming(infer_ms=5),
    )
    parsed = InferResponse.model_validate_json(resp.model_dump_json())
    assert isinstance(parsed.output, RawAsrOutput)


def test_model_info_defaults():
    info = ModelInfo(id="m1", task=Task.OCR, kind="opensource", runner="fake")
    assert info.loaded is False
    assert info.available is True
