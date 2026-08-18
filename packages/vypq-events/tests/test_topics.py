from vypq_contracts.common import Task
from vypq_events.envelope import EventEnvelope
from vypq_events.schemas.inference import InferenceRequested
from vypq_events.topics import dlq_topic, request_topic, result_topic


def test_topic_names():
    assert request_topic(Task.OCR) == "infer.ocr.requests"
    assert result_topic(Task.OCR) == "infer.ocr.results"
    assert dlq_topic(Task.ASR) == "infer.asr.dlq"


def test_envelope_new_generates_ids():
    payload = InferenceRequested(task=Task.OCR, input_uri="s3://b/a.jpg")
    env = EventEnvelope[InferenceRequested].new("inference.requested", payload)
    assert env.event_id
    assert env.trace_id
    assert env.event_type == "inference.requested"


def test_envelope_roundtrip_preserves_payload():
    payload = InferenceRequested(
        task=Task.OCR, input_uri="s3://b/a.jpg", model_version="m1", eval_job_id="e1"
    )
    env = EventEnvelope[InferenceRequested].new("inference.requested", payload)
    parsed = EventEnvelope[InferenceRequested].model_validate_json(env.model_dump_json())
    assert parsed.payload.model_version == "m1"
    assert parsed.payload.eval_job_id == "e1"
    assert parsed.trace_id == env.trace_id


def test_envelope_reuses_supplied_trace_id():
    payload = InferenceRequested(task=Task.OCR, input_uri="s3://b/a.jpg")
    env = EventEnvelope[InferenceRequested].new("x", payload, trace_id="trace-9")
    assert env.trace_id == "trace-9"
