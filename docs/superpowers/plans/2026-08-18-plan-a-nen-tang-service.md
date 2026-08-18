# Plan A — Nền tảng Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng nền tảng để OCR và ASR chạy được qua cả HTTP lẫn Kafka, gọi model trên máy GPU thuê theo giờ, và test được trọn vẹn trên máy không có GPU.

**Architecture:** `model-host` (máy GPU) load model và trả kết quả thô. `services/*` (máy ứng dụng, CPU, stateless) làm pre/post-processing rồi map về contract chuẩn, gọi model-host qua HTTP có retry + circuit breaker. Mỗi service có hai entrypoint — FastAPI và Kafka worker — cùng gọi một `handler`. Backend được tách thành interface nên toàn bộ test chạy được không cần GPU.

**Tech Stack:** Python 3.12, uv workspace, FastAPI, Pydantic v2, httpx, aiokafka, structlog, pytest + pytest-asyncio + respx, Redpanda, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-18-vypq-ai-services-platform-design.md`

## Global Constraints

- Python **3.12** cố định (`requires-python = ">=3.12,<3.13"`). Python hệ thống trên máy dev là 3.9 — luôn dùng `uv run`, không gọi `python3` trực tiếp.
- Quản lí package bằng **uv workspace**. Mọi lệnh chạy qua `uv run`, không dùng `pip install` thủ công.
- Pydantic **v2** (`pydantic>=2.9`), settings qua `pydantic-settings>=2.5`.
- Mọi biến môi trường dùng tiền tố `VYPQ_`, lồng nhau bằng `__`.
- Test **không được yêu cầu GPU**. Test cần GPU phải đánh dấu `@pytest.mark.slow` và bị loại khỏi lệnh mặc định.
- Chuẩn hoá Unicode tiếng Việt: dạng **NFC**, áp dụng ở `postprocess` trước khi trả kết quả.
- Truyền file tới model-host mặc định `multipart/form-data` (**không** base64).
- `model-host` **từ chối khởi động nếu token rỗng**.
- Chỉ retry lỗi kết nối và HTTP 5xx. **Không bao giờ retry 4xx.**
- **Mỗi khi tạo một workspace member mới, phải đăng ký nó vào root `pyproject.toml`** ở cả
  `[dependency-groups] dev` lẫn `[tool.uv.sources]`. `uv sync` chỉ cài những gì được tham
  chiếu tới; member không ai tham chiếu sẽ không có trong venv và `import` sẽ hỏng. Root
  `pyproject.toml` có hai dòng đánh dấu `# <<< workspace members` và `# <<< workspace sources`
  để chèn vào đúng chỗ. Nếu `uv sync` chạy lúc `src/` còn rỗng, uv cache lại kết quả
  đó — lần sync sau sẽ không cài lại. Gặp `ModuleNotFoundError` dù đã đăng ký đúng thì
  chạy `uv sync --reinstall-package <tên-package>`.
- **`uv run ruff check .` phải sạch trước khi commit** (chạy `--fix` cho phần tự sửa được).
  Không để cảnh báo tích lũy sang task sau.
- Commit sau mỗi task. Message theo Conventional Commits, tiếng Anh cho prefix, mô tả tiếng Việt.

## File Structure

| File | Trách nhiệm |
|---|---|
| `pyproject.toml` | uv workspace root, dependency chung cho dev/test |
| `packages/vypq-contracts/src/vypq_contracts/common.py` | Enum dùng chung: `Task`, `ModelKind`, `ErrorCode`, `HealthStatus`, `ErrorResponse`, `HealthResponse` |
| `packages/vypq-contracts/src/vypq_contracts/ocr.py` | `TextBox`, `OcrResult`, `OcrRequest`, `OcrResponse`, `RawOcrOutput` |
| `packages/vypq-contracts/src/vypq_contracts/asr.py` | `Segment`, `AsrResult`, `AsrRequest`, `AsrResponse`, `RawAsrOutput` |
| `packages/vypq-contracts/src/vypq_contracts/hosting.py` | `ModelInfo`, `ModelsResponse`, `InferRequest`, `InferResponse`, `InferTiming` |
| `packages/vypq-core/src/vypq_core/config.py` | `BaseServiceSettings` |
| `packages/vypq-core/src/vypq_core/logging.py` | structlog JSON + contextvar `trace_id` |
| `packages/vypq-core/src/vypq_core/errors.py` | `ServiceError` + exception handler |
| `packages/vypq-core/src/vypq_core/app.py` | `create_app()` — FastAPI factory, `/health`, `/ready` |
| `packages/vypq-core/src/vypq_core/breaker.py` | `CircuitBreaker` — thuần logic, clock tiêm được |
| `packages/vypq-core/src/vypq_core/http_client.py` | `UpstreamClient` — retry + backoff + breaker |
| `packages/vypq-core/src/vypq_core/host_registry.py` | `HostRef`, `HostRegistry` Protocol, `StaticHostRegistry` |
| `packages/vypq-events/src/vypq_events/topics.py` | Hàm sinh tên topic |
| `packages/vypq-events/src/vypq_events/envelope.py` | `EventEnvelope[T]` |
| `packages/vypq-events/src/vypq_events/schemas/inference.py` | `InferenceRequested/Completed/Failed` |
| `packages/vypq-events/src/vypq_events/producer.py` | `EventProducer` |
| `packages/vypq-events/src/vypq_events/consumer.py` | `EventConsumer` — retry, DLQ, pause theo gate |
| `apps/model-host/models.yaml` | Nguồn sự thật về model trên host này |
| `apps/model-host/src/model_host/spec.py` | `ModelSpec`, `HostConfig` đọc từ YAML |
| `apps/model-host/src/model_host/runners/base.py` | `ModelRunner` Protocol |
| `apps/model-host/src/model_host/runners/fake.py` | Runner giả cho test — không cần GPU |
| `apps/model-host/src/model_host/runners/paddle.py` | Runner PaddleOCR thật |
| `apps/model-host/src/model_host/registry.py` | Lazy load, LRU evict theo `vram_budget_mb` |
| `apps/model-host/src/model_host/auth.py` | Bearer token dependency |
| `apps/model-host/src/model_host/api/routes.py` | `/v1/infer`, `/v1/infer/upload`, `/v1/models` |
| `apps/model-host/src/model_host/main.py` | Entrypoint |
| `services/ocr/src/ocr_service/backend/base.py` | `OcrBackend` Protocol |
| `services/ocr/src/ocr_service/backend/remote.py` | Gọi model-host |
| `services/ocr/src/ocr_service/backend/fake.py` | Backend giả cho test |
| `services/ocr/src/ocr_service/pipeline/preprocess.py` | EXIF orientation, giới hạn cạnh dài |
| `services/ocr/src/ocr_service/pipeline/postprocess.py` | Sắp thứ tự đọc, ghép `full_text`, chuẩn hoá NFC |
| `services/ocr/src/ocr_service/handler.py` | Logic dùng chung cho HTTP và Kafka |
| `services/ocr/src/ocr_service/main.py` | HTTP entrypoint |
| `services/ocr/src/ocr_service/worker.py` | Kafka entrypoint |
| `services/_template/` | Khung sinh service mới |
| `scripts/new-service.sh` | Sinh service từ template |

---
### Task 1: Workspace và bộ khung test

**Files:**
- Create: `pyproject.toml`, `.python-version`, `pytest.ini`, `Makefile`
- Create: `packages/vypq-contracts/pyproject.toml`
- Create: `packages/vypq-contracts/src/vypq_contracts/__init__.py`
- Test: `tests/test_workspace.py`

**Interfaces:**
- Consumes: (không có — task đầu tiên)
- Produces: uv workspace với member `packages/*`, `apps/*`, `services/*`. Lệnh `uv run pytest` chạy được. Marker `slow` đã đăng ký.

- [ ] **Step 1: Tạo file pin Python và workspace root**

`.python-version`:
```
3.12
```

`pyproject.toml`:
```toml
[project]
name = "vypq-services"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[tool.uv.workspace]
members = ["packages/*", "apps/*", "services/*"]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "respx>=0.21",
    "ruff>=0.7",
    "vypq-contracts",
    # <<< workspace members
]

[tool.uv.sources]
vypq-contracts = { workspace = true }
# <<< workspace sources

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

Hai mục cuối của `dev` và cả khối `[tool.uv.sources]` là **bắt buộc**, không phải trang trí:
`uv sync` chỉ cài những package được tham chiếu tới. Khai báo `vypq-contracts` trong
`[tool.uv.workspace] members` mới chỉ nói "nó thuộc workspace này", chưa khiến nó được cài vào
venv — thiếu hai dòng trên thì `import vypq_contracts` hỏng với `ModuleNotFoundError`, dù
`uv run pytest` chạy đúng cú pháp. Hai dòng `# <<<` là mốc để các task sau chèn member mới
vào; đừng xoá.

`pytest.ini`:
```ini
[pytest]
testpaths = tests packages services apps
asyncio_mode = auto
markers =
    slow: cần GPU hoặc dịch vụ ngoài, không chạy mặc định
addopts = -m "not slow" --strict-markers --import-mode=importlib
```

`--import-mode=importlib` là bắt buộc, không phải tuỳ chọn: plan có hai file `test_api.py`
(`apps/model-host`, `services/ocr`) và hai file `test_pipeline.py` (`services/ocr`,
`services/asr`). Với import-mode mặc định, pytest sinh tên module từ basename nên hai file
trùng tên sẽ làm nó dừng với `import file mismatch`. Chế độ importlib sinh tên theo đường dẫn
đầy đủ nên không va chạm. Đánh đổi: các file test **không** import được lẫn nhau
(`from conftest import ...` sẽ hỏng), nên helper phải nằm ngay trong file test dùng nó.

`testpaths` liệt kê cả `services` và `apps` — pytest dừng với lỗi nếu một đường dẫn trong đó
không tồn tại, mà hai thư mục này phải đến Task 8 mới có. Tạo sẵn ở bước sau.

- [ ] **Step 2: Tạo sẵn thư mục cho testpaths**

```bash
mkdir -p tests packages services apps
touch services/.gitkeep apps/.gitkeep
```

- [ ] **Step 3: Tạo package vypq-contracts rỗng**

`packages/vypq-contracts/pyproject.toml`:
```toml
[project]
name = "vypq-contracts"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["pydantic>=2.9"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vypq_contracts"]
```

`packages/vypq-contracts/src/vypq_contracts/__init__.py`:
```python
__all__: list[str] = []
```

- [ ] **Step 4: Viết test xác nhận workspace hoạt động**

`tests/test_workspace.py`:
```python
import sys

import vypq_contracts


def test_python_version_is_312():
    assert sys.version_info[:2] == (3, 12)


def test_contracts_package_importable():
    assert vypq_contracts.__all__ == []
```

- [ ] **Step 5: Chạy test**

Chạy: `uv run pytest tests/test_workspace.py -v`
Mong đợi: 2 PASS. Nếu `uv` chưa tải Python 3.12, nó tự tải ở lần chạy đầu.

- [ ] **Step 6: Tạo Makefile**

`Makefile`:
```makefile
.PHONY: test test-all lint fmt
test:
	uv run pytest
test-all:
	uv run pytest -m ""
lint:
	uv run ruff check .
fmt:
	uv run ruff format .
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .python-version pytest.ini Makefile packages tests services apps
git commit -m "chore: khởi tạo uv workspace và bộ khung test"
```

---

### Task 2: vypq-contracts — schema dùng chung

**Files:**
- Create: `packages/vypq-contracts/src/vypq_contracts/common.py`
- Create: `packages/vypq-contracts/src/vypq_contracts/ocr.py`
- Create: `packages/vypq-contracts/src/vypq_contracts/asr.py`
- Create: `packages/vypq-contracts/src/vypq_contracts/hosting.py`
- Test: `packages/vypq-contracts/tests/test_schemas.py`

**Interfaces:**
- Consumes: workspace từ Task 1.
- Produces:
  - `Task` (enum: `OCR="ocr"`, `ASR="asr"`), `ModelKind` (`OPENSOURCE`, `FINETUNED`), `ErrorCode` (`BAD_INPUT`, `MODEL_UNAVAILABLE`, `UPSTREAM_TIMEOUT`, `UPSTREAM_ERROR`, `CIRCUIT_OPEN`, `INTERNAL`), `HealthStatus` (`OK`, `DEGRADED`, `DOWN`)
  - `ErrorResponse(code, message, trace_id)`, `HealthResponse(status, service, version, detail)`
  - `TextBox(id: int, polygon: list[tuple[float,float]], text: str, confidence: float|None, ignore: bool)`
  - `RawOcrOutput(boxes: list[TextBox])`, `OcrResult(full_text: str, boxes: list[TextBox])`
  - `OcrResponse(trace_id, model_version, result: OcrResult, latency_ms)`
  - `Segment(start, end, text, speaker)`, `RawAsrOutput(segments)`, `AsrResult(text, segments)`, `AsrResponse(trace_id, model_version, result, latency_ms)`
  - `ModelInfo(id, task, kind, runner, loaded, available, vram_mb, base, trained_on)`, `ModelsResponse(host_name, models)`
  - `InferRequest(model_id, input_uri, params)`, `InferTiming(load_ms, infer_ms)`
  - `InferResponse(model_id, task, output, timing)` — có `model_validator(mode="before")` chọn kiểu `output` theo `task`; wire format không đổi

- [ ] **Step 1: Viết test trước cho common và ocr**

`packages/vypq-contracts/tests/test_schemas.py`:
```python
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


def test_infer_response_uses_task_when_output_is_empty():
    # Payload rỗng khớp cả hai member của union; chỉ `task` mới phân biệt được.
    resp = InferResponse.model_validate(
        {"model_id": "m", "task": "asr", "output": {}, "timing": {"infer_ms": 1}}
    )
    assert isinstance(resp.output, RawAsrOutput)


def test_infer_response_rejects_output_that_contradicts_task():
    with pytest.raises(ValidationError):
        InferResponse.model_validate(
            {
                "model_id": "m",
                "task": "asr",
                "output": {"boxes": [{"id": 0, "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
                                      "text": "a"}]},
                "timing": {"infer_ms": 1},
            }
        )


def test_infer_response_does_not_silently_drop_half_of_a_mixed_payload():
    with pytest.raises(ValidationError):
        InferResponse.model_validate(
            {
                "model_id": "m",
                "task": "asr",
                "output": {"boxes": [], "segments": [{"start": 0, "end": 1, "text": "a"}]},
                "timing": {"infer_ms": 1},
            }
        )


def test_infer_response_rejects_wrong_output_type_built_in_python():
    # model-host dựng InferResponse trực tiếp, không qua JSON — đường này cũng phải chặn.
    with pytest.raises(ValidationError):
        InferResponse(
            model_id="m",
            task=Task.ASR,
            output=RawOcrOutput(boxes=[]),
            timing=InferTiming(infer_ms=1),
        )


def test_model_info_defaults():
    info = ModelInfo(id="m1", task=Task.OCR, kind="opensource", runner="fake")
    assert info.loaded is False
    assert info.available is True
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Chạy: `uv run pytest packages/vypq-contracts -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'vypq_contracts.common'`

- [ ] **Step 3: Viết common.py**

`packages/vypq-contracts/src/vypq_contracts/common.py`:
```python
from enum import StrEnum

from pydantic import BaseModel, Field


class Task(StrEnum):
    # StrEnum chứ không phải (str, Enum): f"{Task.OCR}" phải ra "ocr", không phải
    # "Task.OCR". Các task sau nội suy enum này vào tên Kafka topic và trường log.
    OCR = "ocr"
    ASR = "asr"


class ModelKind(StrEnum):
    OPENSOURCE = "opensource"
    FINETUNED = "finetuned"


class ErrorCode(StrEnum):
    BAD_INPUT = "bad_input"
    MODEL_UNAVAILABLE = "model_unavailable"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_ERROR = "upstream_error"
    CIRCUIT_OPEN = "circuit_open"
    INTERNAL = "internal"


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    trace_id: str | None = None


class HealthResponse(BaseModel):
    status: HealthStatus
    service: str
    version: str
    detail: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: Viết ocr.py**

`packages/vypq-contracts/src/vypq_contracts/ocr.py`:
```python
from pydantic import BaseModel, Field

Polygon = list[tuple[float, float]]


class TextBox(BaseModel):
    id: int
    polygon: Polygon = Field(min_length=4)
    text: str
    confidence: float | None = None
    ignore: bool = False


class RawOcrOutput(BaseModel):
    """Kết quả thô từ model-host: chỉ có box, chưa sắp thứ tự đọc."""

    boxes: list[TextBox] = Field(default_factory=list)


class OcrResult(BaseModel):
    """Kết quả đã qua postprocess của service."""

    full_text: str
    boxes: list[TextBox] = Field(default_factory=list)


class OcrRequest(BaseModel):
    image_uri: str | None = None
    model_version: str | None = None


class OcrResponse(BaseModel):
    trace_id: str
    model_version: str
    result: OcrResult
    latency_ms: int
```

- [ ] **Step 5: Viết asr.py**

`packages/vypq-contracts/src/vypq_contracts/asr.py`:
```python
from pydantic import BaseModel, Field


class Segment(BaseModel):
    start: float
    end: float
    text: str
    speaker: str | None = None


class RawAsrOutput(BaseModel):
    segments: list[Segment] = Field(default_factory=list)


class AsrResult(BaseModel):
    text: str
    segments: list[Segment] = Field(default_factory=list)


class AsrRequest(BaseModel):
    audio_uri: str | None = None
    model_version: str | None = None


class AsrResponse(BaseModel):
    trace_id: str
    model_version: str
    result: AsrResult
    latency_ms: int
```

- [ ] **Step 6: Viết hosting.py**

`packages/vypq-contracts/src/vypq_contracts/hosting.py`:
```python
from typing import Any

from pydantic import BaseModel, Field, model_validator

from vypq_contracts.asr import RawAsrOutput
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.ocr import RawOcrOutput

RawOutput = RawOcrOutput | RawAsrOutput

_OUTPUT_BY_TASK: dict[Task, type[BaseModel]] = {
    Task.OCR: RawOcrOutput,
    Task.ASR: RawAsrOutput,
}


class ModelInfo(BaseModel):
    id: str
    task: Task
    kind: ModelKind
    runner: str
    loaded: bool = False
    available: bool = True
    vram_mb: int = 0
    base: str | None = None
    trained_on: str | None = None


class ModelsResponse(BaseModel):
    host_name: str
    models: list[ModelInfo] = Field(default_factory=list)


class InferRequest(BaseModel):
    model_id: str
    input_uri: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class InferTiming(BaseModel):
    load_ms: int = 0
    infer_ms: int


class InferResponse(BaseModel):
    model_id: str
    task: Task
    output: RawOutput
    timing: InferTiming

    @model_validator(mode="before")
    @classmethod
    def _resolve_output_by_task(cls, data: Any) -> Any:
        """Chọn kiểu output theo `task`, không để pydantic tự đoán.

        RawOcrOutput và RawAsrOutput đều có field mặc định rỗng, nên payload `{}`
        khớp member đầu tiên của union bất kể task là gì — model trả rỗng (ảnh
        không có chữ) sẽ âm thầm ra RawOcrOutput ngay cả khi task=ASR. Payload
        mang cả 'boxes' lẫn 'segments' còn tệ hơn: một nửa dữ liệu bị vứt lặng lẽ.
        """
        if not isinstance(data, dict):
            return data
        raw_task, output = data.get("task"), data.get("output")
        if raw_task is None:
            return data
        expected = _OUTPUT_BY_TASK[Task(raw_task)]
        if isinstance(output, BaseModel):
            # Đường dựng thẳng trong Python: model-host tạo InferResponse với
            # output=runner.predict(...). Không kiểm ở đây thì runner khai task=ocr
            # mà trả RawAsrOutput vẫn lọt, vì union nhận cả hai.
            if not isinstance(output, expected):
                raise ValueError(
                    f"output là {type(output).__name__} nhưng task={raw_task!r} "
                    f"cần {expected.__name__}"
                )
            return data
        if not isinstance(output, dict):
            return data
        allowed = set(expected.model_fields)
        if unexpected := set(output) - allowed:
            # RawOcrOutput/RawAsrOutput mặc định bỏ qua field lạ (extra="ignore"),
            # nên nếu không chặn ở đây, field của task kia bị vứt lặng lẽ thay vì báo lỗi.
            raise ValueError(
                f"output có field {sorted(unexpected)} không hợp lệ với "
                f"task={raw_task!r} (chỉ chấp nhận {sorted(allowed)})"
            )
        return {**data, "output": expected.model_validate(output)}
```

- [ ] **Step 7: Chạy test để xác nhận pass**

Chạy: `uv run pytest packages/vypq-contracts -v`
Mong đợi: 16 PASS

- [ ] **Step 8: Commit**

```bash
git add packages/vypq-contracts
git commit -m "feat(contracts): schema dùng chung cho ocr, asr và model hosting"
```

---
### Task 3: vypq-core — config, logging, errors, app factory

**Files:**
- Create: `packages/vypq-core/pyproject.toml`
- Create: `packages/vypq-core/src/vypq_core/{__init__,config,logging,errors,app}.py`
- Test: `packages/vypq-core/tests/test_app.py`

**Interfaces:**
- Consumes: `vypq_contracts.common.{ErrorCode, ErrorResponse, HealthResponse, HealthStatus}`
- Produces:
  - `BaseServiceSettings(service_name: str, version: str, log_level: str, port: int)` — đọc env tiền tố `VYPQ_`
  - `ServiceError(code: ErrorCode, message: str, http_status: int)`
  - `setup_logging(level: str) -> None`, `set_trace_id(v: str) -> None`, `get_trace_id() -> str`
  - `HealthCheck = Callable[[], Awaitable[tuple[HealthStatus, str]]]`
  - `create_app(settings: BaseServiceSettings, *, routers: Sequence[APIRouter] = (), readiness: Mapping[str, HealthCheck] = {}, lifespan=None) -> FastAPI` — gắn sẵn `GET /health` và `GET /ready`

- [ ] **Step 1: Tạo pyproject cho vypq-core**

`packages/vypq-core/pyproject.toml`:
```toml
[project]
name = "vypq-core"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "vypq-contracts",
    "fastapi>=0.115",
    "pydantic-settings>=2.5",
    "structlog>=24.4",
    "httpx>=0.27",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vypq_core"]

[tool.uv.sources]
vypq-contracts = { workspace = true }
```

Đăng ký member mới vào root `pyproject.toml` — chèn ngay TRƯỚC dòng đánh dấu tương ứng:

```toml
# trong [dependency-groups] dev, trước "# <<< workspace members":
    "asgi-lifespan>=2.1",
    "vypq-core",

# trong [tool.uv.sources], trước "# <<< workspace sources":
vypq-core = { workspace = true }
```

Rồi chạy `uv sync` và xác nhận `uv run python -c "import vypq_core"` không lỗi. Bỏ bước này
thì mọi test của task hỏng với `ModuleNotFoundError`.

- [ ] **Step 2: Viết test trước**

`packages/vypq-core/tests/test_app.py`:
```python
import httpx
import pytest
from fastapi import APIRouter

from vypq_contracts.common import ErrorCode, HealthStatus
from vypq_core.app import create_app
from vypq_core.config import BaseServiceSettings
from vypq_core.errors import ServiceError
from vypq_core.logging import get_trace_id, set_trace_id

SETTINGS = BaseServiceSettings(service_name="demo", version="9.9.9")


def _client(app, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
    # raise_app_exceptions=False cần cho test handler `Exception`: Starlette gửi
    # response xong vẫn raise lại exception gốc lên ASGI, và ASGITransport mặc
    # định ném nó cho caller. Production dưới uvicorn không có vấn đề này.
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
        base_url="http://t",
    )


async def test_health_is_ok_even_when_dependencies_are_down():
    async def failing():
        return HealthStatus.DOWN, "upstream chết"

    app = create_app(SETTINGS, readiness={"upstream": failing})
    async with _client(app) as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_ready_reports_degraded_when_a_check_is_down():
    async def failing():
        return HealthStatus.DOWN, "upstream chết"

    app = create_app(SETTINGS, readiness={"upstream": failing})
    async with _client(app) as c:
        resp = await c.get("/ready")
    body = resp.json()
    assert resp.status_code == 503
    assert body["status"] == "degraded"
    assert body["detail"]["upstream"] == "upstream chết"


async def test_ready_is_ok_when_all_checks_pass():
    async def fine():
        return HealthStatus.OK, "sẵn sàng"

    app = create_app(SETTINGS, readiness={"upstream": fine})
    async with _client(app) as c:
        resp = await c.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_service_error_becomes_error_envelope_without_traceback():
    router = APIRouter()

    @router.get("/boom")
    async def boom():
        raise ServiceError(ErrorCode.BAD_INPUT, "ảnh hỏng", http_status=422)

    app = create_app(SETTINGS, routers=[router])
    async with _client(app) as c:
        resp = await c.get("/boom")
    body = resp.json()
    assert resp.status_code == 422
    assert body["code"] == "bad_input"
    assert body["message"] == "ảnh hỏng"
    # Middleware luôn gán trace_id, kể cả khi client không gửi — nếu không thì log
    # của mọi request bình thường mất khả năng tương quan.
    assert len(body["trace_id"]) == 32
    assert resp.headers["x-trace-id"] == body["trace_id"]


async def test_unexpected_exception_is_masked_as_internal():
    router = APIRouter()

    @router.get("/crash")
    async def crash():
        raise RuntimeError("chi tiết nội bộ không được lộ ra")

    app = create_app(SETTINGS, routers=[router])
    async with _client(app, raise_app_exceptions=False) as c:
        resp = await c.get("/crash")
    body = resp.json()
    assert resp.status_code == 500
    assert body["code"] == "internal"
    assert "chi tiết nội bộ" not in body["message"]


async def test_trace_id_is_generated_when_client_supplies_none():
    router = APIRouter()

    @router.get("/echo")
    async def echo():
        return {"seen": get_trace_id()}

    app = create_app(SETTINGS, routers=[router])
    async with _client(app) as c:
        resp = await c.get("/echo")
    # Cái log nhìn thấy và cái trả về header phải là một, nếu không thì vô dụng.
    assert resp.json()["seen"] == resp.headers["x-trace-id"]
    assert len(resp.headers["x-trace-id"]) == 32


async def test_incoming_trace_id_header_is_reused_not_replaced():
    router = APIRouter()

    @router.get("/echo")
    async def echo():
        return {"seen": get_trace_id()}

    app = create_app(SETTINGS, routers=[router])
    async with _client(app) as c:
        resp = await c.get("/echo", headers={"x-trace-id": "trace-tu-gateway"})
    assert resp.json()["seen"] == "trace-tu-gateway"
    assert resp.headers["x-trace-id"] == "trace-tu-gateway"


def test_trace_id_defaults_to_dash_and_can_be_set():
    assert get_trace_id() == "-"
    set_trace_id("abc123")
    assert get_trace_id() == "abc123"


def test_settings_read_env_with_vypq_prefix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VYPQ_SERVICE_NAME", "ocr")
    monkeypatch.setenv("VYPQ_PORT", "8123")
    s = BaseServiceSettings()
    assert s.service_name == "ocr"
    assert s.port == 8123
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Chạy: `uv run pytest packages/vypq-core -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'vypq_core'`

- [ ] **Step 4: Viết config.py**

`packages/vypq-core/src/vypq_core/config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VYPQ_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: str = "unnamed"
    version: str = "0.1.0"
    log_level: str = "INFO"
    port: int = 8000
```

- [ ] **Step 5: Viết logging.py**

`packages/vypq-core/src/vypq_core/logging.py`:
```python
import logging
from contextvars import ContextVar

import structlog

_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")


def set_trace_id(value: str) -> None:
    _trace_id.set(value)


def get_trace_id() -> str:
    return _trace_id.get()


def _inject_trace_id(_logger, _method, event_dict):
    event_dict["trace_id"] = get_trace_id()
    return event_dict


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper()))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_trace_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
```

- [ ] **Step 6: Viết errors.py**

`packages/vypq-core/src/vypq_core/errors.py`:
```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vypq_contracts.common import ErrorCode, ErrorResponse
from vypq_core.logging import get_logger, get_trace_id

log = get_logger(__name__)


class ServiceError(Exception):
    def __init__(self, code: ErrorCode, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _envelope(code: ErrorCode, message: str, status: int) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, trace_id=_trace_or_none())
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _trace_or_none() -> str | None:
    trace = get_trace_id()
    return None if trace == "-" else trace


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _handle_service_error(_request: Request, exc: ServiceError):
        log.warning("service_error", code=exc.code.value, message=exc.message)
        return _envelope(exc.code, exc.message, exc.http_status)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception):
        # Ghi traceback vào log, nhưng không bao giờ trả ra ngoài.
        log.exception("unhandled_error", error=str(exc))
        return _envelope(ErrorCode.INTERNAL, "internal server error", 500)
```

- [ ] **Step 7: Viết app.py**

`packages/vypq-core/src/vypq_core/app.py`:
```python
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from vypq_contracts.common import HealthResponse, HealthStatus
from vypq_core.config import BaseServiceSettings
from vypq_core.errors import install_error_handlers
from vypq_core.logging import set_trace_id, setup_logging

HealthCheck = Callable[[], Awaitable[tuple[HealthStatus, str]]]

_WORST = {HealthStatus.OK: 0, HealthStatus.DEGRADED: 1, HealthStatus.DOWN: 2}


def create_app(
    settings: BaseServiceSettings,
    *,
    routers: Sequence[APIRouter] = (),
    readiness: Mapping[str, HealthCheck] | None = None,
    lifespan=None,
    expose_docs: bool = True,
    expose_ready_detail: bool = True,
) -> FastAPI:
    setup_logging(settings.log_level)
    # /docs và /openapi.json nằm ngoài mọi router nên không dính dependency auth.
    # Service nào phơi ra Internet (model-host qua ngrok) phải tắt, nếu không là
    # trao không toàn bộ sơ đồ route và schema cho bất kỳ ai dò ra URL.
    app = FastAPI(
        title=settings.service_name,
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    checks: Mapping[str, HealthCheck] = readiness or {}

    @app.middleware("http")
    async def _trace_middleware(request: Request, call_next):
        # Luôn gán, kể cả khi client không gửi: log và error envelope đều lấy từ
        # đây, nên gán có điều kiện sẽ làm mọi request thường mất trace trong log.
        # Middleware này KHÔNG bắt exception — việc đó thuộc install_error_handlers,
        # để chỉ có một chỗ dựng error envelope.
        trace = request.headers.get("x-trace-id") or uuid.uuid4().hex
        set_trace_id(trace)
        response = await call_next(request)
        response.headers["x-trace-id"] = trace
        return response

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        # Liveness: tiến trình còn sống là ok, không phụ thuộc upstream.
        return HealthResponse(
            status=HealthStatus.OK, service=settings.service_name, version=settings.version
        )

    @app.get("/ready")
    async def ready() -> JSONResponse:
        detail: dict[str, str] = {}
        worst = HealthStatus.OK
        for name, check in checks.items():
            status, note = await check()
            detail[name] = note
            if _WORST[status] > _WORST[worst]:
                worst = status
        # DOWN của một dependency = service degraded, không phải chết hẳn.
        overall = HealthStatus.OK if worst is HealthStatus.OK else HealthStatus.DEGRADED
        body = HealthResponse(
            status=overall,
            service=settings.service_name,
            version=settings.version,
            # /ready phải mở để probe hạ tầng gọi được, nên nó không qua auth.
            # Với service phơi ra Internet thì trạng thái ok/degraded là đủ; tên
            # check và chuỗi chẩn đoán bên trong không nên phát cho người lạ.
            detail=detail if expose_ready_detail else {},
        )
        code = 200 if overall is HealthStatus.OK else 503
        return JSONResponse(status_code=code, content=body.model_dump(mode="json"))

    for router in routers:
        app.include_router(router)

    install_error_handlers(app)
    return app
```

`packages/vypq-core/src/vypq_core/__init__.py`:
```python
__all__: list[str] = []
```

- [ ] **Step 8: Chạy test để xác nhận pass**

Chạy: `uv run pytest packages/vypq-core -v`
Mong đợi: 9 PASS

- [ ] **Step 9: Commit**

```bash
git add packages/vypq-core pyproject.toml
git commit -m "feat(core): app factory, config, logging json và error envelope"
```

---

### Task 4: vypq-core — circuit breaker

**Files:**
- Create: `packages/vypq-core/src/vypq_core/breaker.py`
- Test: `packages/vypq-core/tests/test_breaker.py`

**Interfaces:**
- Consumes: `vypq_core.errors.ServiceError`, `vypq_contracts.common.ErrorCode`
- Produces:
  - `CircuitState` (enum: `CLOSED`, `OPEN`, `HALF_OPEN`)
  - `CircuitBreaker(failure_threshold: int = 5, recovery_timeout_s: float = 30.0, clock: Callable[[], float] = time.monotonic)` với `.state`, `.allow() -> bool`, `.record_success()`, `.record_failure()`
  - `CircuitOpenError(ServiceError)`

Đồng hồ tiêm được qua tham số `clock` để test không phải `sleep`.

- [ ] **Step 1: Viết test trước**

`packages/vypq-core/tests/test_breaker.py`:
```python
from vypq_core.breaker import CircuitBreaker, CircuitState


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(clock: FakeClock) -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=3, recovery_timeout_s=30.0, clock=clock)


def test_starts_closed_and_allows():
    b = _breaker(FakeClock())
    assert b.state is CircuitState.CLOSED
    assert b.allow() is True


def test_opens_after_threshold_consecutive_failures():
    b = _breaker(FakeClock())
    for _ in range(3):
        b.record_failure()
    assert b.state is CircuitState.OPEN
    assert b.allow() is False


def test_success_resets_failure_count():
    b = _breaker(FakeClock())
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.state is CircuitState.CLOSED


def test_moves_to_half_open_after_recovery_timeout():
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    assert b.allow() is False
    clock.advance(30.0)
    assert b.allow() is True
    assert b.state is CircuitState.HALF_OPEN


def test_half_open_success_closes_circuit():
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    clock.advance(31.0)
    b.allow()
    b.record_success()
    assert b.state is CircuitState.CLOSED
    assert b.allow() is True


def test_half_open_failure_reopens_immediately():
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    clock.advance(31.0)
    b.allow()
    b.record_failure()
    assert b.state is CircuitState.OPEN
    assert b.allow() is False


def test_stale_probe_does_not_wedge_the_circuit_forever():
    # Caller nhận probe rồi biến mất, không record_success cũng không record_failure.
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    clock.advance(31.0)
    assert b.allow() is True

    clock.advance(31.0)
    assert b.allow() is False                 # probe treo bị thu hồi, circuit mở lại
    assert b.state is CircuitState.OPEN

    clock.advance(31.0)
    assert b.allow() is True                  # tự hồi phục, cấp probe mới


def test_late_success_from_a_reclaimed_probe_does_not_close_the_circuit():
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    clock.advance(31.0)
    assert b.allow() is True          # probe đi ra
    clock.advance(31.0)
    b.allow()                         # probe bị thu hồi → OPEN
    assert b.state is CircuitState.OPEN
    b.record_success()                # caller cũ mới báo về
    assert b.state is CircuitState.OPEN


def test_late_failure_from_a_reclaimed_probe_does_not_push_back_the_deadline():
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    clock.advance(31.0)
    b.allow()
    clock.advance(31.0)
    b.allow()                         # thu hồi probe, hạn chờ tính từ đây
    clock.advance(5.0)
    b.record_failure()                # caller cũ báo về muộn
    clock.advance(25.0)
    assert b.allow() is True          # đúng hạn 30s, không bị đẩy lùi thêm 5s


def test_half_open_allows_only_one_probe():
    clock = FakeClock()
    b = _breaker(clock)
    for _ in range(3):
        b.record_failure()
    clock.advance(31.0)
    assert b.allow() is True
    assert b.allow() is False
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest packages/vypq-core/tests/test_breaker.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'vypq_core.breaker'`

- [ ] **Step 3: Viết breaker.py**

`packages/vypq-core/src/vypq_core/breaker.py`:
```python
import time
from collections.abc import Callable
from enum import Enum

from vypq_contracts.common import ErrorCode
from vypq_core.errors import ServiceError


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(ServiceError):
    def __init__(self, target: str) -> None:
        super().__init__(
            ErrorCode.CIRCUIT_OPEN,
            f"circuit đang mở cho {target}",
            http_status=503,
        )


class CircuitBreaker:
    """Mở sau N lỗi liên tiếp, half-open sau T giây, đóng lại khi probe thành công."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = failure_threshold
        self._recovery = recovery_timeout_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_started_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return CircuitState.CLOSED
        if self._probe_started_at is not None:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        now = self._clock()
        if self._probe_started_at is not None:
            if now - self._probe_started_at < self._recovery:
                # Half-open chỉ cho đúng một request thăm dò đi qua.
                return False
            # Probe treo: caller đi ra mà không bao giờ báo lại (exception thoát ở
            # nhánh không record, task bị cancel, tiến trình chết giữa chừng).
            # Không có mốc thời gian này thì breaker kẹt HALF_OPEN vĩnh viễn và
            # chặn mọi request về sau, im lặng, không cách nào tự hồi phục.
            self._probe_started_at = None
            self._opened_at = now
            return False
        if now - self._opened_at >= self._recovery:
            self._probe_started_at = now
            return True
        return False

    def _is_late_report(self) -> bool:
        """Báo cáo đến từ một request không còn được phép tồn tại.

        OPEN mà không có probe nào đang bay nghĩa là allow() đang chặn tất cả —
        nên mọi record_* lúc này đều từ caller cũ báo về muộn: probe đã bị thu
        hồi, hoặc request đi qua trước lúc mạch mở. Nhận vào thì một caller treo
        lâu có thể đóng lại mạch đang mở, hoặc đẩy lùi hạn chờ vô cớ.
        """
        return self._opened_at is not None and self._probe_started_at is None

    def record_success(self) -> None:
        if self._is_late_report():
            return
        self._failures = 0
        self._opened_at = None
        self._probe_started_at = None

    def record_failure(self) -> None:
        if self._is_late_report():
            return
        if self._probe_started_at is not None:
            # Probe hỏng → mở lại ngay, tính lại thời gian chờ.
            self._probe_started_at = None
            self._opened_at = self._clock()
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()

    def is_open(self) -> bool:
        """True cả khi OPEN lẫn HALF_OPEN — dùng để báo /ready degraded.

        Đừng dùng hàm này để chặn vòng lặp: HALF_OPEN chính là lúc phải cho một
        request đi qua. Nơi nào cần quyết định gửi hay không thì gọi `allow()`.
        """
        return self.state is not CircuitState.CLOSED
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Chạy: `uv run pytest packages/vypq-core/tests/test_breaker.py -v`
Mong đợi: 17 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/vypq-core
git commit -m "feat(core): circuit breaker với đồng hồ tiêm được"
```

---
### Task 5: vypq-core — UpstreamClient (retry + backoff + breaker)

**Files:**
- Create: `packages/vypq-core/src/vypq_core/http_client.py`
- Test: `packages/vypq-core/tests/test_http_client.py`

**Interfaces:**
- Consumes: `vypq_core.breaker.{CircuitBreaker, CircuitOpenError}`, `vypq_core.errors.ServiceError`
- Produces:
  - `UpstreamError(ServiceError)` — lỗi tạm thời, đáng retry
  - `UpstreamClient(base_url: str, *, token: str | None = None, timeout_s: float = 60.0, max_attempts: int = 3, base_delay_s: float = 0.2, breaker: CircuitBreaker | None = None, client: httpx.AsyncClient | None = None, sleep=asyncio.sleep, jitter=random.random)`
  - `await UpstreamClient.request(method: str, path: str, **kw) -> httpx.Response`
  - `await UpstreamClient.aclose() -> None`
  - Thuộc tính `.breaker`

- [ ] **Step 1: Viết test trước**

`packages/vypq-core/tests/test_http_client.py`:
```python
import asyncio

import httpx
import pytest
import respx

from vypq_core.breaker import CircuitBreaker, CircuitOpenError, CircuitState
from vypq_core.errors import ServiceError
from vypq_core.http_client import UpstreamClient, UpstreamError

BASE = "http://gpu-box:9001"


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _noop_sleep(_seconds: float) -> None:
    return None


def _client(**kw) -> UpstreamClient:
    kw.setdefault("sleep", _noop_sleep)
    kw.setdefault("jitter", lambda: 0.0)
    return UpstreamClient(BASE, **kw)


@respx.mock
async def test_returns_response_on_success():
    respx.get(f"{BASE}/v1/models").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with _client() as c:
        resp = await c.request("GET", "/v1/models")
    assert resp.json() == {"ok": True}


@respx.mock
async def test_retries_on_500_then_succeeds():
    route = respx.get(f"{BASE}/v1/models").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={"ok": True})]
    )
    async with _client(max_attempts=3) as c:
        resp = await c.request("GET", "/v1/models")
    assert resp.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_does_not_retry_on_400():
    route = respx.get(f"{BASE}/v1/models").mock(return_value=httpx.Response(400, text="sai"))
    async with _client(max_attempts=3) as c:
        with pytest.raises(ServiceError) as exc:
            await c.request("GET", "/v1/models")
    assert route.call_count == 1
    assert exc.value.http_status == 400
    assert not isinstance(exc.value, UpstreamError)


@respx.mock
async def test_retries_on_connect_error_then_raises_upstream_error():
    route = respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ConnectError("từ chối"))
    async with _client(max_attempts=3) as c:
        with pytest.raises(UpstreamError):
            await c.request("GET", "/v1/models")
    assert route.call_count == 3


@respx.mock
async def test_timeout_is_reported_as_upstream_error():
    respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ReadTimeout("quá hạn"))
    async with _client(max_attempts=1) as c:
        with pytest.raises(UpstreamError):
            await c.request("GET", "/v1/models")


@respx.mock
async def test_breaker_opens_after_repeated_failures_and_short_circuits():
    route = respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ConnectError("từ chối"))
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=30.0)
    async with _client(max_attempts=1, breaker=breaker) as c:
        for _ in range(2):
            with pytest.raises(UpstreamError):
                await c.request("GET", "/v1/models")
        assert breaker.state is CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            await c.request("GET", "/v1/models")
    # Lần thứ ba bị chặn tại chỗ, không gửi request nào ra ngoài.
    assert route.call_count == 2


@respx.mock
async def test_4xx_does_not_trip_the_breaker():
    respx.get(f"{BASE}/v1/models").mock(return_value=httpx.Response(422))
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_s=30.0)
    async with _client(max_attempts=1, breaker=breaker) as c:
        for _ in range(3):
            with pytest.raises(ServiceError):
                await c.request("GET", "/v1/models")
    assert breaker.state is CircuitState.CLOSED


@respx.mock
async def test_bad_input_4xx_during_half_open_probe_closes_the_circuit():
    # Host trả 4xx nghĩa là host còn sống. Nếu đường này thoát ra mà không báo
    # gì cho breaker, probe treo lại và circuit kẹt vĩnh viễn.
    respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ConnectError("chết"))
    clock = _FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=30.0, clock=clock)
    async with _client(max_attempts=1, breaker=breaker) as c:
        with pytest.raises(UpstreamError):
            await c.request("GET", "/v1/models")
        assert breaker.state is CircuitState.OPEN

        respx.get(f"{BASE}/v1/models").mock(return_value=httpx.Response(422))
        clock.advance(31.0)
        with pytest.raises(ServiceError):
            await c.request("GET", "/v1/models")
    assert breaker.state is CircuitState.CLOSED


@respx.mock
async def test_429_is_retried_like_a_5xx():
    route = respx.get(f"{BASE}/v1/models").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json={"ok": True})]
    )
    async with _client(max_attempts=3) as c:
        resp = await c.request("GET", "/v1/models")
    assert resp.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_cancelled_request_still_reports_to_the_breaker():
    # Không báo lại thì probe half-open treo và mất hai chu kỳ recovery.
    def _cancel(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    respx.get(f"{BASE}/v1/models").mock(side_effect=_cancel)
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=30.0)
    async with _client(max_attempts=1, breaker=breaker) as c:
        with pytest.raises(asyncio.CancelledError):
            await c.request("GET", "/v1/models")
    assert breaker.state is CircuitState.OPEN


class _CountingBreaker(CircuitBreaker):
    """Đếm số lần báo để bắt regression double-report."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.calls: list[str] = []

    def record_success(self) -> None:
        self.calls.append("success")
        super().record_success()

    def record_failure(self) -> None:
        self.calls.append("failure")
        super().record_failure()


@respx.mock
async def test_exactly_one_breaker_report_on_every_exit_path():
    respx.get(f"{BASE}/ok").mock(return_value=httpx.Response(200, json={}))
    respx.get(f"{BASE}/bad").mock(return_value=httpx.Response(422))
    respx.get(f"{BASE}/redir").mock(return_value=httpx.Response(302, headers={"location": "/z"}))
    respx.get(f"{BASE}/down").mock(side_effect=httpx.ConnectError("x"))

    cases = [("/ok", None), ("/bad", ServiceError), ("/redir", UpstreamError),
             ("/down", UpstreamError)]
    for path, expected in cases:
        breaker = _CountingBreaker(failure_threshold=99, recovery_timeout_s=30.0)
        async with _client(max_attempts=1, breaker=breaker) as c:
            if expected is None:
                await c.request("GET", path)
            else:
                with pytest.raises(expected):
                    await c.request("GET", path)
        assert breaker.calls == [breaker.calls[0]], f"{path} báo {breaker.calls}"
        assert len(breaker.calls) == 1, f"{path} báo {breaker.calls}"


@respx.mock
@pytest.mark.parametrize("status", [401, 403, 404, 405, 302])
async def test_infrastructure_statuses_pause_instead_of_dead_lettering(status):
    # Máy thuê lại đổi token -> 401. Tunnel ngrok chết -> 404 từ edge ngrok.
    # Đây là hạ tầng, không phải dữ liệu hỏng: phải là UpstreamError để consumer
    # dừng chờ, và phải mở circuit để /ready báo degraded.
    respx.get(f"{BASE}/v1/models").mock(
        return_value=httpx.Response(status, headers={"location": "https://x/y"})
    )
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=30.0)
    async with _client(max_attempts=1, breaker=breaker) as c:
        with pytest.raises(UpstreamError):
            await c.request("GET", "/v1/models")
    assert breaker.state is CircuitState.OPEN


@respx.mock
@pytest.mark.parametrize("status", [400, 413, 422])
async def test_bad_input_statuses_stay_permanent(status):
    respx.get(f"{BASE}/v1/models").mock(return_value=httpx.Response(status))
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_s=30.0)
    async with _client(max_attempts=1, breaker=breaker) as c:
        with pytest.raises(ServiceError) as exc:
            await c.request("GET", "/v1/models")
    assert not isinstance(exc.value, UpstreamError)
    assert breaker.state is CircuitState.CLOSED      # host vẫn sống


@respx.mock
async def test_bearer_token_is_sent():
    captured: dict[str, str] = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={})

    respx.get(f"{BASE}/v1/models").mock(side_effect=_record)
    async with _client(token="sekret") as c:
        await c.request("GET", "/v1/models")
    assert captured["auth"] == "Bearer sekret"


@respx.mock
async def test_backoff_delays_grow_exponentially():
    delays: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        delays.append(seconds)

    respx.get(f"{BASE}/v1/models").mock(side_effect=httpx.ConnectError("từ chối"))
    c = UpstreamClient(
        BASE, max_attempts=4, base_delay_s=0.5, sleep=_record_sleep, jitter=lambda: 0.0
    )
    async with c:
        with pytest.raises(UpstreamError):
            await c.request("GET", "/v1/models")
    assert delays == [0.5, 1.0, 2.0]
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest packages/vypq-core/tests/test_http_client.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'vypq_core.http_client'`

- [ ] **Step 3: Viết http_client.py**

`packages/vypq-core/src/vypq_core/http_client.py`:
```python
import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx

from vypq_contracts.common import ErrorCode
from vypq_core.breaker import CircuitBreaker, CircuitOpenError
from vypq_core.errors import ServiceError
from vypq_core.logging import get_logger

log = get_logger(__name__)

# Những mã 4xx nói về HẠ TẦNG chứ không phải nội dung request: host còn sống
# không, token còn đúng không, tunnel còn trỏ đúng chỗ không.
#   401/403 — máy GPU thuê lại đổi token, hoặc token hết hạn
#   404/405 — tunnel ngrok chết, edge của ngrok trả 404 thay cho host
#   408/429 — hết giờ, quá tải
# Xếp nhầm chúng vào "dữ liệu hỏng" thì đổi một cái token là cả hàng đợi đổ vào
# DLQ trong vài giây, mà circuit vẫn đóng nên không hề có backpressure.
_INFRA_STATUS = frozenset({401, 403, 404, 405, 408, 429})


class UpstreamError(ServiceError):
    """Lỗi tạm thời phía upstream — đáng retry và làm sập circuit."""

    def __init__(self, message: str, code: ErrorCode = ErrorCode.UPSTREAM_ERROR) -> None:
        super().__init__(code, message, http_status=503)


class UpstreamClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout_s: float = 60.0,
        max_attempts: int = 3,
        base_delay_s: float = 0.2,
        breaker: CircuitBreaker | None = None,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.breaker = breaker or CircuitBreaker()
        self._max_attempts = max_attempts
        self._base_delay = base_delay_s
        self._sleep = sleep
        self._jitter = jitter
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout_s, headers=headers
        )

    async def __aenter__(self) -> "UpstreamClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self.breaker.allow():
            raise CircuitOpenError(self.base_url)

        reported = False
        try:
            last: Exception | None = None
            for attempt in range(1, self._max_attempts + 1):
                try:
                    response = await self._client.request(method, path, **kwargs)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    code = (
                        ErrorCode.UPSTREAM_TIMEOUT
                        if isinstance(exc, httpx.TimeoutException)
                        else ErrorCode.UPSTREAM_ERROR
                    )
                    last = UpstreamError(f"{self.base_url}: {exc}", code)
                else:
                    if 300 <= response.status_code < 400:
                        # httpx không tự đi theo redirect. Hay gặp khi base_url để
                        # http:// mà ngrok chuyển sang https://. Xếp vào hạ tầng:
                        # dừng chờ và mở circuit để /ready báo degraded, còn hơn
                        # đổ hàng đợi vào DLQ vì một dòng cấu hình sai.
                        last = UpstreamError(
                            f"{self.base_url} trả redirect {response.status_code} tới "
                            f"{response.headers.get('location', '?')} — kiểm tra base_url"
                        )
                    elif response.status_code < 400:
                        reported = True
                        self.breaker.record_success()
                        return response
                    elif response.status_code >= 500 or response.status_code in _INFRA_STATUS:
                        last = UpstreamError(f"{self.base_url} trả {response.status_code}")
                    else:
                        # 400/413/422 và các 4xx còn lại là lỗi của chính request,
                        # thử lại vẫn sai → không retry.
                        # Nhưng host phải còn sống mới trả được 4xx, nên record_success:
                        # thoát ra mà không báo gì sẽ để probe half-open treo.
                        reported = True
                        self.breaker.record_success()
                        raise ServiceError(
                            ErrorCode.BAD_INPUT,
                            f"upstream từ chối ({response.status_code}): {response.text[:200]}",
                            http_status=response.status_code,
                        )

                if attempt < self._max_attempts:
                    delay = self._base_delay * (2 ** (attempt - 1))
                    await self._sleep(delay + self._jitter() * delay * 0.1)
                    log.warning("upstream_retry", url=self.base_url, attempt=attempt)

            reported = True
            self.breaker.record_failure()
            if last is None:  # pragma: no cover - chỉ xảy ra nếu max_attempts < 1
                raise ValueError(f"max_attempts phải >= 1, đang là {self._max_attempts}")
            raise last
        finally:
            if not reported:
                # Lối thoát bất thường: CancelledError khi caller huỷ, lỗi lập trình,
                # KeyboardInterrupt. Không báo lại thì probe half-open bị bỏ treo và
                # phải mất hai chu kỳ recovery mới phục vụ lại được.
                self.breaker.record_failure()
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Chạy: `uv run pytest packages/vypq-core/tests/test_http_client.py -v`
Mong đợi: 14 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/vypq-core
git commit -m "feat(core): UpstreamClient với retry, backoff và circuit breaker"
```

---

### Task 6: vypq-core — host registry

**Files:**
- Create: `packages/vypq-core/src/vypq_core/host_registry.py`
- Test: `packages/vypq-core/tests/test_host_registry.py`

**Interfaces:**
- Consumes: `vypq_contracts.hosting.ModelInfo`, `vypq_contracts.common.{ErrorCode, Task}`, `vypq_core.errors.ServiceError`
- Produces:
  - `HostRef(name: str, url: str, token: str | None, models: list[ModelInfo], healthy: bool, inflight: int)` — có `.has_model(model_id) -> bool`
  - `NoHostAvailableError(ServiceError)` — code `MODEL_UNAVAILABLE`, http 503
  - `HostRegistry` Protocol: `await hosts() -> list[HostRef]`, `await pick(model_id: str) -> HostRef`, `models_for_task(task: Task) -> list[ModelInfo]`, context manager `lease(host)` tăng/giảm `inflight`
  - `StaticHostRegistry(hosts: list[HostRef])`

Plan B sẽ thêm `DiscoveryHostRegistry` cùng Protocol này. Plan A chỉ cần bản static.

- [ ] **Step 1: Viết test trước**

`packages/vypq-core/tests/test_host_registry.py`:
```python
import pytest

from vypq_contracts.common import ModelKind, Task
from vypq_contracts.hosting import ModelInfo
from vypq_core.host_registry import (
    HostRef,
    HostRegistry,
    NoHostAvailableError,
    StaticHostRegistry,
)


def _model(mid: str, task: Task = Task.OCR, available: bool = True) -> ModelInfo:
    return ModelInfo(
        id=mid, task=task, kind=ModelKind.OPENSOURCE, runner="fake", available=available
    )


def _host(name: str, models: list[ModelInfo], healthy: bool = True) -> HostRef:
    return HostRef(name=name, url=f"http://{name}:9000", models=models, healthy=healthy)


async def test_pick_returns_host_that_has_the_model():
    reg = StaticHostRegistry([_host("a", [_model("m1")]), _host("b", [_model("m2")])])
    assert (await reg.pick("m2")).name == "b"


async def test_pick_skips_unhealthy_hosts():
    reg = StaticHostRegistry(
        [_host("a", [_model("m1")], healthy=False), _host("b", [_model("m1")])]
    )
    assert (await reg.pick("m1")).name == "b"


async def test_pick_skips_hosts_where_model_is_unavailable():
    reg = StaticHostRegistry(
        [_host("a", [_model("m1", available=False)]), _host("b", [_model("m1")])]
    )
    assert (await reg.pick("m1")).name == "b"


async def test_pick_chooses_least_inflight():
    a = _host("a", [_model("m1")])
    b = _host("b", [_model("m1")])
    a.inflight = 3
    b.inflight = 1
    reg = StaticHostRegistry([a, b])
    assert (await reg.pick("m1")).name == "b"


async def test_pick_raises_when_no_host_has_the_model():
    reg = StaticHostRegistry([_host("a", [_model("m1")])])
    with pytest.raises(NoHostAvailableError):
        await reg.pick("khong-ton-tai")


async def test_lease_increments_then_decrements_inflight():
    host = _host("a", [_model("m1")])
    reg = StaticHostRegistry([host])
    async with reg.lease(host):
        assert host.inflight == 1
    assert host.inflight == 0


async def test_lease_decrements_even_when_body_raises():
    host = _host("a", [_model("m1")])
    reg = StaticHostRegistry([host])
    with pytest.raises(RuntimeError):
        async with reg.lease(host):
            raise RuntimeError("hỏng")
    assert host.inflight == 0


def test_static_registry_satisfies_the_protocol():
    # Nếu Protocol thiếu lease(), bản discovery ở Plan B có thể quên mà không ai biết.
    assert isinstance(StaticHostRegistry([]), HostRegistry)


def test_models_for_task_marks_unavailable_when_only_unhealthy_hosts_have_it():
    reg = StaticHostRegistry([_host("a", [_model("m1")], healthy=False)])
    models = reg.models_for_task(Task.OCR)
    assert len(models) == 1                 # vẫn liệt kê để biết model tồn tại
    assert models[0].available is False      # nhưng không hứa là dùng được


async def test_catalogue_agrees_with_pick():
    # available=True phải tương đương "pick() sẽ thành công", không hơn không kém.
    reg = StaticHostRegistry(
        [_host("a", [_model("m1", available=False)]), _host("b", [_model("m1")], healthy=False)]
    )
    assert reg.models_for_task(Task.OCR)[0].available is False
    with pytest.raises(NoHostAvailableError):
        await reg.pick("m1")


def test_models_for_task_prefers_the_available_copy():
    reg = StaticHostRegistry(
        [_host("a", [_model("m1", available=False)]), _host("b", [_model("m1")])]
    )
    models = reg.models_for_task(Task.OCR)
    assert len(models) == 1
    assert models[0].available is True


async def test_models_for_task_filters_and_dedupes():
    reg = StaticHostRegistry(
        [
            _host("a", [_model("m1"), _model("m9", task=Task.ASR)]),
            _host("b", [_model("m1"), _model("m2")]),
        ]
    )
    ids = sorted(m.id for m in reg.models_for_task(Task.OCR))
    assert ids == ["m1", "m2"]
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest packages/vypq-core/tests/test_host_registry.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'vypq_core.host_registry'`

- [ ] **Step 3: Viết host_registry.py**

`packages/vypq-core/src/vypq_core/host_registry.py`:
```python
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from vypq_contracts.common import ErrorCode, Task
from vypq_contracts.hosting import ModelInfo
from vypq_core.errors import ServiceError


class NoHostAvailableError(ServiceError):
    def __init__(self, model_id: str) -> None:
        super().__init__(
            ErrorCode.MODEL_UNAVAILABLE,
            f"không có host khoẻ nào phục vụ model '{model_id}'",
            http_status=503,
        )


class HostRef(BaseModel):
    name: str
    url: str
    token: str | None = None
    models: list[ModelInfo] = Field(default_factory=list)
    healthy: bool = True
    inflight: int = 0

    def has_model(self, model_id: str) -> bool:
        return any(m.id == model_id and m.available for m in self.models)


@runtime_checkable
class HostRegistry(Protocol):
    async def hosts(self) -> list[HostRef]: ...
    async def pick(self, model_id: str) -> HostRef: ...
    def models_for_task(self, task: Task) -> list[ModelInfo]: ...
    # lease() phải nằm trong Protocol: Plan B thay bằng bản discovery, thiếu khai
    # báo ở đây thì bản đó quên cài mà type checker không kêu, chỉ vỡ lúc chạy.
    # Lưu ý @runtime_checkable chỉ kiểm method CÓ MẶT, không kiểm chữ ký: một bản
    # cài lease() thành hàm sync vẫn qua được isinstance.
    def lease(self, host: HostRef) -> AbstractAsyncContextManager[HostRef]: ...


class StaticHostRegistry:
    """Danh sách host cố định từ config. Plan B thay bằng DiscoveryHostRegistry."""

    def __init__(self, hosts: list[HostRef]) -> None:
        self._hosts = hosts

    async def hosts(self) -> list[HostRef]:
        return list(self._hosts)

    async def pick(self, model_id: str) -> HostRef:
        candidates = [h for h in self._hosts if h.healthy and h.has_model(model_id)]
        if not candidates:
            raise NoHostAvailableError(model_id)
        return min(candidates, key=lambda h: h.inflight)

    def models_for_task(self, task: Task) -> list[ModelInfo]:
        """Danh mục model, hiểu đúng theo nghĩa `pick()` dùng.

        `available=True` nghĩa là NGAY LÚC NÀY có host khoẻ phục vụ được — tức là
        `pick()` sẽ thành công. Nếu không, model vẫn được liệt kê nhưng
        `available=False`: bỏ hẳn khỏi danh mục thì không ai biết nó tồn tại, còn
        báo available trong khi `pick()` từ chối thì tệ hơn cả hai, vì caller tin
        danh mục để định tuyến rồi ăn 503.

        Xét cả `host.healthy` chứ không chỉ `model.available`: chỉ nhìn
        `model.available` sẽ báo khoẻ cho model nằm trên một máy thuê đã tắt.
        """
        best: dict[str, tuple[int, ModelInfo]] = {}
        for host in self._hosts:
            for model in host.models:
                if model.task is not task:
                    continue
                servable = host.healthy and model.available
                current = best.get(model.id)
                if current is not None and current[0] >= int(servable):
                    continue
                entry = model if servable else model.model_copy(update={"available": False})
                best[model.id] = (int(servable), entry)
        return [entry for _rank, entry in best.values()]

    @asynccontextmanager
    async def lease(self, host: HostRef):
        host.inflight += 1
        try:
            yield host
        finally:
            host.inflight -= 1
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Chạy: `uv run pytest packages/vypq-core/tests/test_host_registry.py -v`
Mong đợi: 10 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/vypq-core
git commit -m "feat(core): host registry tĩnh, chọn host ít request đang chạy nhất"
```

---
### Task 7: vypq-events — topic, envelope, producer, consumer

Đây là task quan trọng nhất của Plan A. Yêu cầu cốt lõi từ spec mục 3.5: **khi upstream chết,
worker phải dừng consume, không được đẩy message vào DLQ.** Nếu làm sai, một lần GPU sập sẽ
đổ nguyên hàng đợi vào dead-letter.

**Files:**
- Create: `packages/vypq-events/pyproject.toml`
- Create: `packages/vypq-events/src/vypq_events/{__init__,topics,envelope,producer,consumer}.py`
- Create: `packages/vypq-events/src/vypq_events/schemas/{__init__,inference}.py`
- Test: `packages/vypq-events/tests/{test_topics,test_consumer}.py`

**Interfaces:**
- Consumes: `vypq_contracts.common.{ErrorCode, Task}`, `vypq_core.breaker.CircuitOpenError`, `vypq_core.http_client.UpstreamError`
- Produces:
  - `request_topic(task) -> str`, `result_topic(task) -> str`, `dlq_topic(task) -> str`, `CRAWL_DOCUMENTS_READY: str`
  - `EventEnvelope[T](event_id, event_type, trace_id, occurred_at, payload: T)` với classmethod `new(event_type, payload, trace_id=None) -> EventEnvelope[T]`
  - `InferenceRequested`, `InferenceCompleted`, `InferenceFailed`
  - `EventProducer(brokers, producer=None)` — `start()`, `stop()`, `publish(topic, envelope, key=None)`
  - `EventConsumer(...)` — `run_once() -> int`, `run()`
  - `default_is_retryable(exc) -> bool`

- [ ] **Step 1: Tạo pyproject**

`packages/vypq-events/pyproject.toml`:
```toml
[project]
name = "vypq-events"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["vypq-contracts", "vypq-core", "aiokafka>=0.11", "pydantic>=2.9"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vypq_events"]

[tool.uv.sources]
vypq-contracts = { workspace = true }
vypq-core = { workspace = true }
```

Đăng ký vào root `pyproject.toml`: thêm `"vypq-events",` trước `# <<< workspace members`
và `vypq-events = { workspace = true }` trước `# <<< workspace sources`, rồi `uv sync`.

- [ ] **Step 2: Viết test cho topics và envelope**

`packages/vypq-events/tests/test_topics.py`:
```python
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
```

- [ ] **Step 3: Viết topics.py, envelope.py, schemas/inference.py**

`packages/vypq-events/src/vypq_events/topics.py`:
```python
from vypq_contracts.common import Task

CRAWL_DOCUMENTS_READY = "crawl.documents.ready"


def request_topic(task: Task) -> str:
    return f"infer.{task.value}.requests"


def result_topic(task: Task) -> str:
    return f"infer.{task.value}.results"


def dlq_topic(task: Task) -> str:
    return f"infer.{task.value}.dlq"
```

`packages/vypq-events/src/vypq_events/envelope.py`:
```python
import uuid
from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class EventEnvelope(BaseModel, Generic[T]):
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
```

`packages/vypq-events/src/vypq_events/schemas/inference.py`:
```python
from typing import Any

from pydantic import BaseModel, Field

from vypq_contracts.common import ErrorCode, Task


class InferenceRequested(BaseModel):
    task: Task
    input_uri: str
    model_version: str | None = None
    eval_job_id: str | None = None
    dataset_item_id: str | None = None


class InferenceCompleted(BaseModel):
    task: Task
    model_version: str
    input_uri: str
    output: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int
    eval_job_id: str | None = None
    dataset_item_id: str | None = None


class InferenceFailed(BaseModel):
    task: Task
    input_uri: str
    code: ErrorCode
    message: str
    attempts: int
    model_version: str | None = None
    eval_job_id: str | None = None
    dataset_item_id: str | None = None
```

`packages/vypq-events/src/vypq_events/schemas/__init__.py` và `packages/vypq-events/src/vypq_events/__init__.py`:
```python
__all__: list[str] = []
```

- [ ] **Step 4: Chạy test topics**

Chạy: `uv run pytest packages/vypq-events/tests/test_topics.py -v`
Mong đợi: 4 PASS

- [ ] **Step 5: Viết fake Kafka — đặt ngay đầu `test_consumer.py`**

Không dùng `conftest.py`: `--import-mode=importlib` khiến `from conftest import ...` hỏng.
Phần dưới đây là đầu file `packages/vypq-events/tests/test_consumer.py`:
```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TP:
    topic: str
    partition: int = 0


@dataclass
class FakeMessage:
    value: bytes
    offset: int
    topic: str = "infer.ocr.requests"
    partition: int = 0
    key: bytes | None = None


@dataclass
class FakeConsumer:
    """Thay aiokafka.AIOKafkaConsumer trong unit test."""

    batches: list[dict] = field(default_factory=list)
    committed: int = 0
    paused_tps: set = field(default_factory=set)
    seeks: list[tuple] = field(default_factory=list)
    _tp: TP = field(default_factory=lambda: TP("infer.ocr.requests", 0))

    async def getmany(self, timeout_ms: int = 1000, max_records: int | None = None):
        # Consumer thật trả rỗng cho partition đang pause. Fake phải giống, nếu
        # không test sẽ thấy message vẫn chảy vào lúc đang dừng, và ta sẽ đi sửa
        # nhầm production code cho khớp một cái fake sai.
        if self.paused_tps or not self.batches:
            return {}
        return self.batches.pop(0)

    def assignment(self):
        return {self._tp}

    def paused(self):
        return set(self.paused_tps)

    def pause(self, *tps):
        self.paused_tps.update(tps)

    def resume(self, *tps):
        self.paused_tps.difference_update(tps)

    def seek(self, tp, offset):
        self.seeks.append((tp, offset))

    async def commit(self):
        self.committed += 1


@dataclass
class FakeProducer:
    published: list[tuple] = field(default_factory=list)

    async def publish(self, topic, envelope, key=None):
        self.published.append((topic, envelope, key))
```

- [ ] **Step 6: Viết test cho consumer**

Tiếp nối cùng file `packages/vypq-events/tests/test_consumer.py`:
```python
import pytest

from vypq_contracts.common import Task
from vypq_core.breaker import CircuitOpenError
from vypq_core.host_registry import NoHostAvailableError
from vypq_core.http_client import UpstreamError
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import EventEnvelope
from vypq_events.schemas.inference import InferenceRequested

TOPIC_TP = TP("infer.ocr.requests", 0)


def _msg(offset: int, uri: str = "s3://b/a.jpg") -> FakeMessage:
    env = EventEnvelope[InferenceRequested].new(
        "inference.requested", InferenceRequested(task=Task.OCR, input_uri=uri)
    )
    return FakeMessage(value=env.model_dump_json().encode(), offset=offset)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


async def _noop_sleep(_s: float) -> None:
    return None


def _consumer(kafka, producer, handler, clock=None, **kw) -> EventConsumer:
    return EventConsumer(
        topic="infer.ocr.requests",
        group_id="ocr-default",
        handler=handler,
        dlq_topic="infer.ocr.dlq",
        producer=producer,
        consumer=kafka,
        sleep=_noop_sleep,
        clock=clock or Clock(),
        max_attempts=kw.pop("max_attempts", 3),
        pause_seconds=kw.pop("pause_seconds", 10.0),
        **kw,
    )


async def test_processes_batch_and_commits():
    seen = []

    async def handler(env):
        seen.append(env)

    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0), _msg(1)]}])
    c = _consumer(kafka, FakeProducer(), handler)
    processed = await c.run_once()
    assert processed == 2
    assert len(seen) == 2
    assert kafka.committed == 1


async def test_permanent_error_goes_to_dlq_and_processing_continues():
    calls = []

    async def handler(env):
        calls.append(env)
        if len(calls) == 1:
            raise ValueError("ảnh hỏng")

    producer = FakeProducer()
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0), _msg(1)]}])
    c = _consumer(kafka, producer, handler)
    processed = await c.run_once()
    assert processed == 2
    assert len(producer.published) == 1
    assert producer.published[0][0] == "infer.ocr.dlq"
    assert kafka.seeks == []


@pytest.mark.parametrize(
    "exc",
    [
        CircuitOpenError("gpu"),
        UpstreamError("gpu chết"),
        # Chưa đăng ký máy thuê, hoặc máy vừa tắt — hạ tầng, không phải dữ liệu.
        NoHostAvailableError("m1"),
    ],
)
async def test_retryable_exhaustion_pauses_and_seeks_back_without_dlq(exc):
    async def handler(_env):
        raise exc

    producer = FakeProducer()
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(5), _msg(6)]}])
    c = _consumer(kafka, producer, handler, max_attempts=2)
    processed = await c.run_once()

    assert processed == 0
    assert producer.published == []          # tuyệt đối không đẩy vào DLQ
    assert kafka.seeks == [(TOPIC_TP, 5)]    # tua về đúng message đang dở
    assert TOPIC_TP in kafka.paused_tps      # đã dừng consume
    assert kafka.committed == 1              # commit tới trước message đó


async def test_retryable_then_success_does_not_pause():
    attempts = []

    async def handler(_env):
        attempts.append(1)
        if len(attempts) == 1:
            raise UpstreamError("chập chờn")

    producer = FakeProducer()
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0)]}])
    c = _consumer(kafka, producer, handler, max_attempts=3)
    processed = await c.run_once()
    assert processed == 1
    assert len(attempts) == 2
    assert kafka.paused_tps == set()
    assert producer.published == []


async def test_malformed_json_goes_to_dlq():
    async def handler(_env):
        raise AssertionError("không bao giờ được gọi")

    producer = FakeProducer()
    bad = FakeMessage(value=b"{khong-phai-json", offset=0)
    kafka = FakeConsumer(batches=[{TOPIC_TP: [bad]}])
    c = _consumer(kafka, producer, handler)
    processed = await c.run_once()
    assert processed == 1
    assert producer.published[0][0] == "infer.ocr.dlq"


async def test_pause_stops_fetching_then_resumes_and_carries_on():
    gpu_down = [True]

    async def handler(_env):
        if gpu_down[0]:
            raise UpstreamError("gpu chết")

    clock = Clock()
    producer = FakeProducer()
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0)]}, {TOPIC_TP: [_msg(1)]}])
    c = _consumer(kafka, producer, handler, clock=clock, max_attempts=1, pause_seconds=10.0)

    await c.run_once()
    assert TOPIC_TP in kafka.paused_tps
    assert len(kafka.batches) == 1            # batch sau chưa bị đụng tới

    clock.advance(5.0)
    await c.run_once()
    assert TOPIC_TP in kafka.paused_tps       # chưa hết cửa sổ chờ, vẫn dừng
    assert len(kafka.batches) == 1            # và tuyệt đối không lấy thêm gì

    gpu_down[0] = False
    clock.advance(6.0)
    processed = await c.run_once()
    assert kafka.paused_tps == set()          # hết cửa sổ → resume
    assert processed == 1                     # và tiêu thụ tiếp được
    assert producer.published == []           # suốt quá trình không DLQ cái nào
```

- [ ] **Step 7: Chạy test để xác nhận fail**

Chạy: `uv run pytest packages/vypq-events/tests/test_consumer.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'vypq_events.consumer'`

- [ ] **Step 8: Viết producer.py**

`packages/vypq-events/src/vypq_events/producer.py`:
```python
from aiokafka import AIOKafkaProducer

from vypq_core.http_client import UpstreamError
from vypq_events.envelope import EventEnvelope


class EventProducer:
    def __init__(self, brokers: str = "localhost:9092", producer=None) -> None:
        self._producer = producer or AIOKafkaProducer(bootstrap_servers=brokers)

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, topic: str, envelope: EventEnvelope, key: str | None = None) -> None:
        # Partition key mặc định là trace_id → mọi event của một request cùng partition.
        partition_key = (key or envelope.trace_id).encode()
        try:
            await self._producer.send_and_wait(
                topic, envelope.model_dump_json().encode(), key=partition_key
            )
        except Exception as exc:
            # aiokafka ném exception riêng của nó, không phải UpstreamError. Không
            # bọc lại thì consumer coi là dữ liệu hỏng và dead-letter — mất luôn
            # kết quả inference ĐÃ CHẠY XONG, tức là vứt đi thời gian GPU đã trả tiền.
            raise UpstreamError(f"không publish được vào {topic}: {exc}") from exc
```

- [ ] **Step 9: Viết consumer.py**

`packages/vypq-events/src/vypq_events/consumer.py`:
```python
import asyncio
import time
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaConsumer

from vypq_core.breaker import CircuitOpenError
from vypq_core.host_registry import NoHostAvailableError
from vypq_core.http_client import UpstreamError
from vypq_core.logging import get_logger, set_trace_id
from vypq_events.envelope import EventEnvelope, RawEnvelope

log = get_logger(__name__)

Handler = Callable[[RawEnvelope], Awaitable[None]]


def default_is_retryable(exc: Exception) -> bool:
    """Lỗi của upstream thì đáng chờ; lỗi của dữ liệu thì không.

    NoHostAvailableError nằm ở đây vì "chưa có host khoẻ nào" là tình trạng hạ
    tầng, không phải dữ liệu hỏng: máy GPU thuê chưa đăng ký xong, hoặc vừa hết
    giờ và tắt. Xếp nhầm nó vào nhóm dữ liệu hỏng thì cả hàng đợi rơi vào DLQ
    đúng lúc không có máy nào chạy — chính thảm hoạ mà cơ chế pause sinh ra để ngăn.
    """
    return isinstance(exc, (CircuitOpenError, UpstreamError, NoHostAvailableError))


class _PauseSignal(Exception):
    """Nội bộ: báo run_once dừng consume thay vì đẩy message vào DLQ."""


class EventConsumer:
    def __init__(
        self,
        *,
        topic: str,
        group_id: str,
        handler: Handler,
        dlq_topic: str,
        producer,
        brokers: str = "localhost:9092",
        consumer=None,
        max_attempts: int = 3,
        base_delay_s: float = 0.5,
        pause_seconds: float = 30.0,
        poll_ms: int = 1000,
        max_records: int = 20,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        is_retryable: Callable[[Exception], bool] = default_is_retryable,
    ) -> None:
        self._handler = handler
        self._dlq_topic = dlq_topic
        self._producer = producer
        self._max_attempts = max_attempts
        self._base_delay = base_delay_s
        self._pause_seconds = pause_seconds
        self._poll_ms = poll_ms
        self._max_records = max_records
        self._sleep = sleep
        self._clock = clock
        self._is_retryable = is_retryable
        self._paused_until: float | None = None
        self._consumer = consumer or AIOKafkaConsumer(
            topic,
            bootstrap_servers=brokers,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )

    async def start(self) -> None:
        await self._consumer.start()

    async def stop(self) -> None:
        await self._consumer.stop()

    async def run(self) -> None:
        while True:
            await self.run_once()

    async def run_once(self) -> int:
        # Vẫn gọi getmany() khi đang pause, không bỏ qua: consumer thật trả rỗng
        # sau timeout_ms nên vòng lặp tự có nhịp, và aiokafka giữ được heartbeat
        # với group. Bỏ poll đi thì run() quay tít không nghỉ.
        self._maybe_resume()
        batch = await self._consumer.getmany(
            timeout_ms=self._poll_ms, max_records=self._max_records
        )
        processed = 0
        # Offset chưa xử lý đầu tiên của TỪNG partition trong batch.
        pending = {tp: msgs[0].offset for tp, msgs in batch.items() if msgs}
        for tp, messages in batch.items():
            for message in messages:
                try:
                    await self._process(message)
                except _PauseSignal:
                    # Tua lại MỌI partition trong batch, không chỉ cái đang lỗi:
                    # commit() không tham số commit vị trí của TẤT CẢ partition
                    # được gán, kể cả những partition mà getmany() đã trả record
                    # nhưng vòng lặp này chưa chạy tới. Chỉ tua một partition thì
                    # số record kia bị commit qua và mất vĩnh viễn — đo được 7/9
                    # message biến mất trên topic 3 partition.
                    for other_tp, offset in pending.items():
                        self._consumer.seek(other_tp, offset)
                    await self._consumer.commit()
                    self._pause()
                    return processed
                pending[tp] = message.offset + 1
                processed += 1
        if processed:
            await self._consumer.commit()
        return processed

    def _pause(self) -> None:
        assignment = self._consumer.assignment()
        if assignment:
            self._consumer.pause(*assignment)
        self._paused_until = self._clock() + self._pause_seconds
        log.warning("consumer_paused", seconds=self._pause_seconds)

    def _maybe_resume(self) -> None:
        if self._paused_until is None:
            return
        if self._clock() < self._paused_until:
            return
        paused = self._consumer.paused()
        if paused:
            self._consumer.resume(*paused)
        self._paused_until = None
        log.info("consumer_resumed")

    async def _process(self, message) -> None:
        try:
            envelope = RawEnvelope.model_validate_json(message.value)
        except Exception as exc:
            log.error("envelope_parse_failed", error=str(exc))
            await self._to_dlq(message, None, exc, attempts=1)
            return

        set_trace_id(envelope.trace_id)
        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._handler(envelope)
                return
            except Exception as exc:
                if not self._is_retryable(exc):
                    await self._to_dlq(message, envelope, exc, attempts=attempt)
                    return
                if attempt == self._max_attempts:
                    log.warning("retry_exhausted_pausing", error=str(exc))
                    raise _PauseSignal from exc
                await self._sleep(self._base_delay * (2 ** (attempt - 1)))

    async def _to_dlq(self, message, envelope, exc: Exception, attempts: int) -> None:
        dead = EventEnvelope[RawEnvelope].new(
            "event.dead_lettered",
            RawEnvelope(
                event_id=getattr(envelope, "event_id", "unknown"),
                event_type=getattr(envelope, "event_type", "unknown"),
                trace_id=getattr(envelope, "trace_id", "unknown"),
                occurred_at=getattr(envelope, "occurred_at", None) or _now(),
                payload={
                    "reason": f"{type(exc).__name__}: {exc}",
                    "attempts": attempts,
                    "raw": message.value.decode("utf-8", errors="replace"),
                },
            ),
        )
        try:
            await self._producer.publish(self._dlq_topic, dead)
        except Exception as dlq_exc:
            # Không ghi được vào DLQ thì tuyệt đối không commit qua message này.
            # Broker đang có vấn đề → coi như sự cố hạ tầng và dừng consume, giống
            # hệt lúc upstream chết. Để exception bay tiếp thì nó không phải
            # _PauseSignal, run_once() không bắt, và cả consumer chết đứng.
            log.error("dlq_publish_failed", topic=self._dlq_topic, error=str(dlq_exc))
            raise _PauseSignal from dlq_exc
        log.error("event_dead_lettered", topic=self._dlq_topic, reason=str(exc))


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
```

- [ ] **Step 10: Chạy test để xác nhận pass**

Chạy: `uv run pytest packages/vypq-events -v`
Mong đợi: 4 + 8 = 12 PASS

- [ ] **Step 11: Thêm Redpanda vào compose và viết test tích hợp**

`infra/compose/docker-compose.dev.yml`:
```yaml
services:
  redpanda:
    image: redpandadata/redpanda:v24.2.7
    command:
      - redpanda start
      - --overprovisioned
      - --smp 1
      - --memory 1G
      - --kafka-addr PLAINTEXT://0.0.0.0:9092
      - --advertise-kafka-addr PLAINTEXT://localhost:9092
    ports: ["9092:9092"]
    healthcheck:
      test: ["CMD-SHELL", "rpk cluster health | grep -q 'Healthy:.*true'"]
      interval: 5s
      retries: 20

  redpanda-console:
    image: redpandadata/console:v2.7.2
    environment:
      KAFKA_BROKERS: redpanda:9092
    ports: ["8090:8080"]
    depends_on: [redpanda]
```

`packages/vypq-events/tests/test_integration_redpanda.py`:
```python
import asyncio
import time

import pytest

from vypq_contracts.common import Task
from vypq_core.http_client import UpstreamError
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import EventEnvelope
from vypq_events.producer import EventProducer
from vypq_events.schemas.inference import InferenceRequested
from vypq_events.topics import dlq_topic, request_topic

pytestmark = pytest.mark.slow
BROKERS = "localhost:9092"


async def test_roundtrip_through_real_redpanda():
    # Topic và group phải là DUY NHẤT mỗi lần chạy. Dùng topic dùng chung thì test
    # nuốt luôn message của lần chạy trước (hoặc của người khác đang thử tay) và
    # fail ngẫu nhiên — "xanh khi môi trường sạch" là loại test tệ hơn không có.
    suffix = str(int(time.time() * 1000))
    topic = f"infer.ocr.requests.roundtrip.{suffix}"
    producer = EventProducer(BROKERS)
    await producer.start()
    received: list = []

    async def handler(env):
        received.append(env)

    consumer = EventConsumer(
        topic=topic,
        group_id=f"test-roundtrip-{suffix}",
        handler=handler,
        dlq_topic=dlq_topic(Task.OCR),
        producer=producer,
        brokers=BROKERS,
    )
    await consumer.start()
    try:
        env = EventEnvelope[InferenceRequested].new(
            "inference.requested",
            InferenceRequested(task=Task.OCR, input_uri="s3://b/a.jpg"),
        )
        await producer.publish(topic, env)
        for _ in range(20):
            if await consumer.run_once():
                break
            await asyncio.sleep(0.5)
    finally:
        await consumer.stop()
        await producer.stop()

    assert len(received) == 1
    assert received[0].payload["input_uri"] == "s3://b/a.jpg"


async def test_retryable_failure_is_redelivered_and_nothing_is_lost():
    """Bảo đảm cốt lõi của cả nền tảng, và chỉ Kafka thật mới chứng minh được.

    FakeConsumer không mô phỏng việc giao lại sau seek() — nó pop nguyên batch ra
    khỏi list. Nên mọi test unit chỉ chứng minh được "có gọi seek", không chứng
    minh được "message quay lại". Đây là chỗ duy nhất kiểm được điều đó.
    """
    suffix = str(int(time.time() * 1000))
    topic = f"infer.ocr.requests.redeliver.{suffix}"
    producer = EventProducer(BROKERS)
    await producer.start()

    handled: list[str] = []
    failed_once: set[str] = set()

    async def handler(env):
        uri = env.payload["input_uri"]
        if uri == "u2" and uri not in failed_once:
            failed_once.add(uri)
            raise UpstreamError("gpu chết giữa chừng")
        handled.append(uri)

    clock_now = [0.0]
    consumer = EventConsumer(
        topic=topic,
        group_id=f"test-redeliver-{suffix}",
        handler=handler,
        dlq_topic=dlq_topic(Task.OCR),
        producer=producer,
        brokers=BROKERS,
        max_attempts=1,
        pause_seconds=1.0,
        clock=lambda: clock_now[0],
    )
    await consumer.start()
    try:
        for uri in ("u1", "u2", "u3"):
            await producer.publish(
                topic,
                EventEnvelope[InferenceRequested].new(
                    "inference.requested",
                    InferenceRequested(task=Task.OCR, input_uri=uri),
                ),
                # Ép cùng partition key: mặc định key là trace_id, mỗi message một
                # giá trị khác nhau. Assert về thứ tự chỉ đúng khi cả ba nằm chung
                # một partition — hiện nay đúng nhờ topic tự tạo có 1 partition,
                # tức là đúng do may chứ không do thiết kế.
                key="cung-mot-partition",
            )
        for _ in range(40):
            await consumer.run_once()
            clock_now[0] += 1.0               # cho qua cửa sổ pause
            if len(handled) == 3:
                break
            await asyncio.sleep(0.2)
    finally:
        await consumer.stop()
        await producer.stop()

    assert handled == ["u1", "u2", "u3"], f"mất hoặc đảo thứ tự: {handled}"
    assert len(handled) == len(set(handled)), f"xử lý trùng: {handled}"
```

- [ ] **Step 12: Chạy test tích hợp với Redpanda thật**

```bash
docker compose -f infra/compose/docker-compose.dev.yml up -d redpanda
uv run pytest packages/vypq-events/tests/test_integration_redpanda.py -m slow -v
```
Mong đợi: 2 PASS. Console xem topic tại http://localhost:8090

- [ ] **Step 13: Commit**

```bash
git add packages/vypq-events infra
git commit -m "feat(events): envelope, producer và consumer dừng-consume thay vì đổ DLQ"
```

---
### Task 8: model-host — registry, VRAM, auth, API

**Files:**
- Create: `apps/model-host/pyproject.toml`, `apps/model-host/models.yaml`
- Create: `apps/model-host/src/model_host/{__init__,settings,spec,registry,auth,main}.py`
- Create: `apps/model-host/src/model_host/runners/{__init__,base,fake}.py`
- Create: `apps/model-host/src/model_host/api/{__init__,routes}.py`
- Test: `apps/model-host/tests/{test_registry,test_api}.py`

**Interfaces:**
- Consumes: `vypq_core.app.create_app`, `vypq_core.config.BaseServiceSettings`, `vypq_core.errors.ServiceError`, `vypq_contracts.hosting.*`
- Produces:
  - `ModelSpec(id, task, kind, runner, source, vram_mb, pinned, base, trained_on, params)`
  - `HostConfig(host_name, vram_budget_mb, models)`, `load_host_config(path: Path) -> HostConfig`
  - `ModelRunner` Protocol: `task: Task`, `load(spec: ModelSpec) -> None`, `unload() -> None`, `predict(data: bytes, params: dict) -> RawOcrOutput | RawAsrOutput`
  - `RunnerFactory = Callable[[str], ModelRunner]`, `RUNNERS: dict[str, RunnerFactory]`
  - `ModelRegistry(config, runners)` — `.infos() -> list[ModelInfo]`, `.acquire(model_id) -> tuple[ModelRunner, ModelSpec, int]` (int = load_ms)
  - `ModelHostSettings(host_name, token, models_path, vram_budget_mb)`
  - Endpoint `GET /v1/models`, `POST /v1/infer`, `POST /v1/infer/upload`

- [ ] **Step 1: Tạo pyproject và models.yaml**

`apps/model-host/pyproject.toml`:
```toml
[project]
name = "model-host"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "vypq-contracts",
    "vypq-core",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "python-multipart>=0.0.12",
    "pyyaml>=6.0",
    "httpx>=0.27",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/model_host"]

[tool.uv.sources]
vypq-contracts = { workspace = true }
vypq-core = { workspace = true }
```

Đăng ký vào root `pyproject.toml`: thêm `"model-host",` trước `# <<< workspace members`
và `model-host = { workspace = true }` trước `# <<< workspace sources`, rồi `uv sync`.

`apps/model-host/models.yaml`:
```yaml
host_name: gpu-1
vram_budget_mb: 20000
models:
  - id: paddleocr-v4-vi
    task: ocr
    kind: opensource
    runner: paddle
    vram_mb: 2500
    pinned: true
    source: {type: hf, repo: PaddlePaddle/PP-OCRv4}
    params: {lang: vi, use_angle_cls: true}
```

- [ ] **Step 2: Viết test cho registry**

`apps/model-host/tests/test_registry.py`:
```python
import pytest

from model_host.registry import ModelRegistry
from model_host.runners.fake import FakeOcrRunner
from model_host.spec import HostConfig, ModelSpec
from vypq_contracts.common import ModelKind, Task
from vypq_core.errors import ServiceError


def _spec(mid: str, vram: int, pinned: bool = False) -> ModelSpec:
    return ModelSpec(
        id=mid, task=Task.OCR, kind=ModelKind.OPENSOURCE, runner="fake",
        vram_mb=vram, pinned=pinned,
    )


def _registry(specs: list[ModelSpec], budget: int) -> ModelRegistry:
    config = HostConfig(host_name="gpu-1", vram_budget_mb=budget, models=specs)
    return ModelRegistry(config, runners={"fake": FakeOcrRunner})


def test_models_are_not_loaded_until_acquired():
    reg = _registry([_spec("m1", 1000)], budget=5000)
    assert reg.infos()[0].loaded is False
    reg.acquire("m1")
    assert reg.infos()[0].loaded is True


def test_acquire_returns_same_runner_instance_on_second_call():
    reg = _registry([_spec("m1", 1000)], budget=5000)
    first, _, load_ms_1 = reg.acquire("m1")
    second, _, load_ms_2 = reg.acquire("m1")
    assert first is second
    assert load_ms_2 == 0  # lần thứ hai không tốn thời gian load


def test_evicts_least_recently_used_when_budget_exceeded():
    reg = _registry([_spec("m1", 3000), _spec("m2", 3000)], budget=5000)
    reg.acquire("m1")
    reg.acquire("m2")
    loaded = {i.id: i.loaded for i in reg.infos()}
    assert loaded == {"m1": False, "m2": True}


def test_pinned_model_is_never_evicted():
    reg = _registry([_spec("m1", 3000, pinned=True), _spec("m2", 3000)], budget=5000)
    reg.acquire("m1")
    with pytest.raises(ServiceError) as exc:
        reg.acquire("m2")
    assert "không đủ VRAM" in exc.value.message
    assert reg.infos()[0].loaded is True


def test_recently_used_model_survives_eviction():
    reg = _registry([_spec("m1", 2000), _spec("m2", 2000), _spec("m3", 2000)], budget=5000)
    reg.acquire("m1")
    reg.acquire("m2")
    reg.acquire("m1")   # m1 vừa dùng → m2 mới là cũ nhất
    reg.acquire("m3")
    loaded = {i.id: i.loaded for i in reg.infos()}
    assert loaded == {"m1": True, "m2": False, "m3": True}


def test_model_larger_than_budget_is_rejected_clearly():
    reg = _registry([_spec("m1", 99000)], budget=5000)
    with pytest.raises(ServiceError) as exc:
        reg.acquire("m1")
    assert "lớn hơn ngân sách" in exc.value.message


def test_unknown_model_raises_service_error():
    reg = _registry([_spec("m1", 1000)], budget=5000)
    with pytest.raises(ServiceError):
        reg.acquire("khong-co")


def test_failed_load_marks_model_unavailable_without_killing_host():
    class Broken(FakeOcrRunner):
        def load(self, spec):
            raise RuntimeError("thiếu checkpoint")

    config = HostConfig(
        host_name="gpu-1", vram_budget_mb=5000,
        models=[_spec("m1", 1000), _spec("m2", 1000)],
    )
    config.models[0].runner = "broken"
    reg = ModelRegistry(config, runners={"fake": FakeOcrRunner, "broken": Broken})
    with pytest.raises(ServiceError):
        reg.acquire("m1")
    infos = {i.id: i for i in reg.infos()}
    assert infos["m1"].available is False
    assert infos["m2"].available is True     # model khác không bị ảnh hưởng
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/model-host -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'model_host'`

- [ ] **Step 4: Viết spec.py và runners**

`apps/model-host/src/model_host/spec.py`:
```python
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from vypq_contracts.common import ModelKind, Task


class ModelSpec(BaseModel):
    id: str
    task: Task
    kind: ModelKind
    runner: str
    vram_mb: int = 0
    pinned: bool = False
    source: dict[str, str] = Field(default_factory=dict)
    base: str | None = None
    trained_on: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class HostConfig(BaseModel):
    host_name: str
    vram_budget_mb: int
    models: list[ModelSpec] = Field(default_factory=list)


def load_host_config(path: Path) -> HostConfig:
    return HostConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
```

`apps/model-host/src/model_host/runners/base.py`:
```python
from typing import Protocol

from model_host.spec import ModelSpec
from vypq_contracts.asr import RawAsrOutput
from vypq_contracts.common import Task
from vypq_contracts.ocr import RawOcrOutput


class ModelRunner(Protocol):
    task: Task

    def load(self, spec: ModelSpec) -> None: ...
    def unload(self) -> None: ...
    def predict(self, data: bytes, params: dict) -> RawOcrOutput | RawAsrOutput: ...
```

`apps/model-host/src/model_host/runners/fake.py`:
```python
from model_host.spec import ModelSpec
from vypq_contracts.asr import RawAsrOutput, Segment
from vypq_contracts.common import Task
from vypq_contracts.ocr import RawOcrOutput, TextBox


class FakeOcrRunner:
    """Runner không cần GPU. Dùng cho test và cho việc chạy thử toàn stack."""

    task = Task.OCR

    def __init__(self) -> None:
        self._spec: ModelSpec | None = None

    def load(self, spec: ModelSpec) -> None:
        self._spec = spec

    def unload(self) -> None:
        self._spec = None

    def predict(self, data: bytes, params: dict) -> RawOcrOutput:
        # Trả box cố định, không phụ thuộc nội dung ảnh — đủ để kiểm hợp đồng.
        return RawOcrOutput(
            boxes=[
                TextBox(id=0, polygon=[(10, 10), (110, 10), (110, 40), (10, 40)],
                        text="XIN CHÀO", confidence=0.99),
                TextBox(id=1, polygon=[(10, 50), (90, 50), (90, 80), (10, 80)],
                        text="thế giới", confidence=0.95),
            ]
        )


class FakeAsrRunner:
    task = Task.ASR

    def load(self, spec: ModelSpec) -> None:
        self._spec = spec

    def unload(self) -> None:
        self._spec = None

    def predict(self, data: bytes, params: dict) -> RawAsrOutput:
        return RawAsrOutput(
            segments=[
                Segment(start=0.0, end=1.2, text="xin chào"),
                Segment(start=1.4, end=2.9, text="thế giới"),
            ]
        )
```

`apps/model-host/src/model_host/runners/__init__.py`:
```python
from model_host.runners.fake import FakeAsrRunner, FakeOcrRunner

RUNNERS: dict[str, type] = {
    "fake": FakeOcrRunner,
    "fake-asr": FakeAsrRunner,
}
```

- [ ] **Step 5: Viết registry.py**

`apps/model-host/src/model_host/registry.py`:
```python
import time
from collections.abc import Callable

from model_host.runners.base import ModelRunner
from model_host.spec import HostConfig, ModelSpec
from vypq_contracts.common import ErrorCode
from vypq_contracts.hosting import ModelInfo
from vypq_core.errors import ServiceError
from vypq_core.logging import get_logger

log = get_logger(__name__)


class _Loaded:
    __slots__ = ("runner", "spec", "last_used")

    def __init__(self, runner: ModelRunner, spec: ModelSpec, last_used: int) -> None:
        self.runner = runner
        self.spec = spec
        self.last_used = last_used


class ModelRegistry:
    """Lazy load, evict LRU theo vram_budget_mb. Model pinned không bao giờ bị evict."""

    def __init__(self, config: HostConfig, runners: dict[str, Callable[[], ModelRunner]]) -> None:
        self._config = config
        self._runners = runners
        self._specs = {spec.id: spec for spec in config.models}
        self._loaded: dict[str, _Loaded] = {}
        self._unavailable: set[str] = set()
        self._tick = 0

    @property
    def host_name(self) -> str:
        return self._config.host_name

    def infos(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id=s.id, task=s.task, kind=s.kind, runner=s.runner, vram_mb=s.vram_mb,
                base=s.base, trained_on=s.trained_on,
                loaded=s.id in self._loaded,
                available=s.id not in self._unavailable,
            )
            for s in self._config.models
        ]

    def acquire(self, model_id: str) -> tuple[ModelRunner, ModelSpec, int]:
        spec = self._specs.get(model_id)
        if spec is None:
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE, f"không có model '{model_id}' trên host này", 404
            )
        if model_id in self._unavailable:
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE, f"model '{model_id}' đang không dùng được", 503
            )

        self._tick += 1
        if entry := self._loaded.get(model_id):
            entry.last_used = self._tick
            return entry.runner, entry.spec, 0

        self._make_room(spec)
        factory = self._runners.get(spec.runner)
        if factory is None:
            raise ServiceError(
                ErrorCode.INTERNAL, f"không biết runner '{spec.runner}'", 500
            )
        started = time.monotonic()
        runner = factory()
        try:
            runner.load(spec)
        except Exception as exc:
            # Một model hỏng không được làm sập cả host.
            self._unavailable.add(model_id)
            log.error("model_load_failed", model_id=model_id, error=str(exc))
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE, f"không load được '{model_id}': {exc}", 503
            ) from exc
        load_ms = int((time.monotonic() - started) * 1000)
        self._loaded[model_id] = _Loaded(runner, spec, self._tick)
        log.info("model_loaded", model_id=model_id, load_ms=load_ms)
        return runner, spec, load_ms

    def _used_mb(self) -> int:
        return sum(e.spec.vram_mb for e in self._loaded.values())

    def _make_room(self, spec: ModelSpec) -> None:
        budget = self._config.vram_budget_mb
        if spec.vram_mb > budget:
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE,
                f"model '{spec.id}' cần {spec.vram_mb}MB, lớn hơn ngân sách {budget}MB",
                503,
            )
        while self._used_mb() + spec.vram_mb > budget:
            evictable = [e for e in self._loaded.values() if not e.spec.pinned]
            if not evictable:
                raise ServiceError(
                    ErrorCode.MODEL_UNAVAILABLE,
                    f"không đủ VRAM cho '{spec.id}': các model đang giữ đều là pinned",
                    503,
                )
            victim = min(evictable, key=lambda e: e.last_used)
            victim.runner.unload()
            del self._loaded[victim.spec.id]
            log.info("model_evicted", model_id=victim.spec.id)
```

- [ ] **Step 6: Chạy test registry**

Chạy: `uv run pytest apps/model-host/tests/test_registry.py -v`
Mong đợi: 8 PASS

- [ ] **Step 7: Viết test cho API**

`apps/model-host/tests/test_api.py`:
```python
import httpx
import pytest

from model_host.api.routes import build_router
from model_host.registry import ModelRegistry
from model_host.runners.fake import FakeOcrRunner
from model_host.settings import ModelHostSettings
from model_host.spec import HostConfig, ModelSpec
from vypq_contracts.common import ModelKind, Task
from vypq_core.app import create_app

TOKEN = "sekret"


def _app(**overrides):
    config = HostConfig(
        host_name="gpu-1", vram_budget_mb=5000,
        models=[ModelSpec(id="m1", task=Task.OCR, kind=ModelKind.OPENSOURCE,
                          runner="fake", vram_mb=1000)],
    )
    registry = ModelRegistry(config, runners={"fake": FakeOcrRunner})
    settings = ModelHostSettings(
        service_name="model-host", token=TOKEN, host_name="gpu-1", **overrides
    )
    return create_app(
        settings,
        routers=[build_router(registry, settings)],
        expose_docs=settings.expose_docs,
    )


def _client(**overrides) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(**overrides)),
        base_url="http://t",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


async def test_models_endpoint_lists_declared_models():
    async with _client() as c:
        resp = await c.get("/v1/models")
    body = resp.json()
    assert resp.status_code == 200
    assert body["host_name"] == "gpu-1"
    assert [m["id"] for m in body["models"]] == ["m1"]


async def test_request_without_token_is_rejected():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t"
    ) as c:
        resp = await c.get("/v1/models")
    assert resp.status_code == 401


async def test_request_with_wrong_token_is_rejected():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://t",
        headers={"Authorization": "Bearer sai"},
    ) as c:
        resp = await c.get("/v1/models")
    assert resp.status_code == 401


async def test_health_does_not_require_token():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t"
    ) as c:
        resp = await c.get("/health")
    assert resp.status_code == 200


async def test_infer_upload_returns_raw_boxes():
    async with _client() as c:
        resp = await c.post(
            "/v1/infer/upload",
            data={"model_id": "m1"},
            files={"file": ("a.jpg", b"\xff\xd8fake-jpeg", "image/jpeg")},
        )
    body = resp.json()
    assert resp.status_code == 200
    assert body["model_id"] == "m1"
    assert body["task"] == "ocr"
    assert body["output"]["boxes"][0]["text"] == "XIN CHÀO"
    assert body["timing"]["infer_ms"] >= 0


async def test_infer_upload_with_unknown_model_returns_404_envelope():
    async with _client() as c:
        resp = await c.post(
            "/v1/infer/upload",
            data={"model_id": "khong-co"},
            files={"file": ("a.jpg", b"x", "image/jpeg")},
        )
    assert resp.status_code == 404
    assert resp.json()["code"] == "model_unavailable"


async def test_file_uri_is_refused_by_default():
    # Host phơi ra Internet: token rò một lần không được kéo theo quyền đọc file.
    async with _client() as c:
        resp = await c.post("/v1/infer", json={"model_id": "m1", "input_uri": "file:///etc/hosts"})
    assert resp.status_code == 400
    assert "file://" in resp.json()["message"]


async def test_ready_does_not_disclose_check_details():
    # /ready mở cho probe nên không qua auth; vì thế không được kể chi tiết.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t"
    ) as c:
        resp = await c.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["detail"] == {}


async def test_docs_are_not_exposed_by_default():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://t"
    ) as c:
        for path in ("/docs", "/openapi.json", "/redoc"):
            assert (await c.get(path)).status_code == 404, path


async def test_infer_by_uri_reads_local_file(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"\xff\xd8fake-jpeg")
    async with _client(allow_file_uri=True) as c:
        resp = await c.post(
            "/v1/infer", json={"model_id": "m1", "input_uri": image.as_uri()}
        )
    assert resp.status_code == 200
    assert resp.json()["output"]["boxes"][1]["text"] == "thế giới"


async def test_infer_by_uri_rejects_unsupported_scheme():
    async with _client() as c:
        resp = await c.post(
            "/v1/infer", json={"model_id": "m1", "input_uri": "s3://bucket/a.jpg"}
        )
    assert resp.status_code == 400
    assert "scheme" in resp.json()["message"]


def test_settings_refuse_empty_token():
    with pytest.raises(ValueError):
        ModelHostSettings(service_name="model-host", token="", host_name="gpu-1")
```

- [ ] **Step 8: Viết settings.py, auth.py, api/routes.py, main.py**

`apps/model-host/src/model_host/settings.py`:
```python
from pathlib import Path

from pydantic import field_validator

from vypq_core.config import BaseServiceSettings


class ModelHostSettings(BaseServiceSettings):
    service_name: str = "model-host"
    host_name: str = "gpu-1"
    token: str = ""
    models_path: Path = Path("models.yaml")
    port: int = 9000
    # Mặc định TẮT: host này phơi ra Internet qua ngrok. Token rò một lần mà bật
    # file:// thì kẻ cầm token đọc được mọi file tiến trình đọc được, không chỉ
    # chạy được inference.
    allow_file_uri: bool = False
    expose_docs: bool = False
    max_download_mb: int = 100
    fetch_deadline_s: float = 60.0

    @field_validator("token")
    @classmethod
    def _token_must_not_be_empty(cls, value: str) -> str:
        # ngrok phơi endpoint ra Internet công cộng: chạy không token là không chấp nhận được.
        if not value.strip():
            raise ValueError("VYPQ_TOKEN bắt buộc phải có — model-host từ chối khởi động")
        return value
```

`apps/model-host/src/model_host/auth.py`:
```python
import secrets

from fastapi import Header

from vypq_contracts.common import ErrorCode
from vypq_core.errors import ServiceError


def make_token_dependency(expected: str):
    async def require_token(authorization: str = Header(default="")) -> None:
        prefix = "Bearer "
        supplied = authorization[len(prefix):] if authorization.startswith(prefix) else ""
        # compare_digest thay vì ==: so sánh chuỗi thường thoát sớm ở byte đầu
        # khác nhau. Qua ngrok thì jitter mạng che gần hết tín hiệu đó, nhưng
        # đây là một dòng code cho thứ duy nhất chặn giữa Internet và GPU.
        if not secrets.compare_digest(supplied, expected):
            raise ServiceError(ErrorCode.BAD_INPUT, "token không hợp lệ", http_status=401)

    return require_token
```

`apps/model-host/src/model_host/api/routes.py`:
```python
import asyncio
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile

from model_host.auth import make_token_dependency
from model_host.registry import ModelRegistry
from model_host.settings import ModelHostSettings
from vypq_contracts.common import ErrorCode
from vypq_contracts.hosting import InferRequest, InferResponse, InferTiming, ModelsResponse
from vypq_core.errors import ServiceError

_SUPPORTED_SCHEMES = {"http", "https", "file"}


async def _fetch(uri: str, *, allow_file: bool, max_bytes: int, deadline_s: float) -> bytes:
    scheme = urlparse(uri).scheme
    if scheme not in _SUPPORTED_SCHEMES:
        raise ServiceError(
            ErrorCode.BAD_INPUT,
            f"scheme '{scheme}' chưa hỗ trợ — dùng http(s) presigned url hoặc file://",
            http_status=400,
        )
    if scheme == "file":
        if not allow_file:
            raise ServiceError(
                ErrorCode.BAD_INPUT,
                "file:// bị tắt trên host này — bật bằng VYPQ_ALLOW_FILE_URI nếu chạy local",
                http_status=400,
            )
        path = Path(urlparse(uri).path)
        if not path.is_file():
            raise ServiceError(ErrorCode.BAD_INPUT, f"không thấy file {path}", 400)
        return path.read_bytes()

    # Đọc theo luồng và cắt khi vượt hạn: `response.content` nạp nguyên body vào
    # RAM, nên một URI trỏ tới file khổng lồ đủ để hạ cả máy GPU.
    # timeout của httpx tính theo từng lần đọc, không phải toàn bộ request: một
    # server nhỏ giọt dưới ngưỡng max_bytes có thể giữ connection vô hạn.
    async with asyncio.timeout(deadline_s):
        return await _stream(uri, max_bytes)


async def _stream(uri: str, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream("GET", uri) as response:
            if response.status_code >= 400:
                raise ServiceError(ErrorCode.BAD_INPUT, f"tải {uri} thất bại", 400)
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ServiceError(
                        ErrorCode.BAD_INPUT,
                        f"input vượt quá {max_bytes // 1024 // 1024}MB",
                        http_status=413,
                    )
                chunks.append(chunk)
    return b"".join(chunks)


def build_router(registry: ModelRegistry, settings: ModelHostSettings) -> APIRouter:
    guard = Depends(make_token_dependency(settings.token))
    router = APIRouter(prefix="/v1", dependencies=[guard])

    def _run(model_id: str, data: bytes, params: dict) -> InferResponse:
        runner, spec, load_ms = registry.acquire(model_id)
        started = time.monotonic()
        output = runner.predict(data, {**spec.params, **params})
        infer_ms = int((time.monotonic() - started) * 1000)
        return InferResponse(
            model_id=model_id,
            task=spec.task,
            output=output,
            timing=InferTiming(load_ms=load_ms, infer_ms=infer_ms),
        )

    @router.get("/models", response_model=ModelsResponse)
    async def list_models() -> ModelsResponse:
        return ModelsResponse(host_name=registry.host_name, models=registry.infos())

    @router.post("/infer", response_model=InferResponse)
    async def infer(request: InferRequest) -> InferResponse:
        if not request.input_uri:
            raise ServiceError(ErrorCode.BAD_INPUT, "thiếu input_uri", 400)
        data = await _fetch(
            request.input_uri,
            allow_file=settings.allow_file_uri,
            max_bytes=settings.max_download_mb * 1024 * 1024,
            deadline_s=settings.fetch_deadline_s,
        )
        return _run(request.model_id, data, request.params)

    @router.post("/infer/upload", response_model=InferResponse)
    async def infer_upload(
        model_id: str = Form(...), file: UploadFile = File(...)
    ) -> InferResponse:
        return _run(model_id, await file.read(), {})

    return router
```

`apps/model-host/src/model_host/main.py`:
```python
from model_host.api.routes import build_router
from model_host.registry import ModelRegistry
from model_host.runners import RUNNERS
from model_host.settings import ModelHostSettings
from model_host.spec import load_host_config
from vypq_core.app import create_app


def build_app():
    settings = ModelHostSettings()
    config = load_host_config(settings.models_path)
    registry = ModelRegistry(config, runners=RUNNERS)
    return create_app(
        settings,
        routers=[build_router(registry, settings)],
        expose_docs=settings.expose_docs,
        expose_ready_detail=False,
    )


app = build_app()
```

`apps/model-host/src/model_host/__init__.py` và `apps/model-host/src/model_host/api/__init__.py`:
```python
__all__: list[str] = []
```

- [ ] **Step 9: Chạy toàn bộ test model-host**

Chạy: `uv run pytest apps/model-host -v`
Mong đợi: 8 + 12 = 20 PASS

- [ ] **Step 10: Chạy thử host thật bằng fake runner**

`apps/model-host/models.dev.yaml` — **commit file này**, Task 11 dùng lại để chạy
end-to-end trên máy không có GPU:
```yaml
host_name: gpu-dev
vram_budget_mb: 4000
models:
  - {id: fake-ocr, task: ocr, kind: opensource, runner: fake, vram_mb: 100, pinned: true}
```

```bash
cd apps/model-host
VYPQ_TOKEN=sekret VYPQ_MODELS_PATH=models.dev.yaml \
  uv run uvicorn model_host.main:app --port 9001 &
sleep 3
curl -s localhost:9001/v1/models -H "Authorization: Bearer sekret" | head -c 300
echo
curl -s -o /dev/null -w "%{http_code}\n" localhost:9001/v1/models
```
Mong đợi: JSON có `fake-ocr`, và request không token trả `401`.

- [ ] **Step 11: Commit**

```bash
git add apps/model-host
git commit -m "feat(model-host): registry lazy-load, evict LRU theo VRAM, bearer token bắt buộc"
```

---

### Task 9: model-host — runner PaddleOCR thật

**Files:**
- Create: `apps/model-host/src/model_host/runners/paddle.py`
- Modify: `apps/model-host/src/model_host/runners/__init__.py`
- Create: `apps/model-host/Dockerfile`
- Create: `apps/model-host/docker-compose.yml`
- Test: `apps/model-host/tests/test_paddle_runner.py`

**Interfaces:**
- Consumes: `ModelRunner` Protocol, `ModelSpec` từ Task 8
- Produces: `PaddleOcrRunner` đăng ký dưới khoá `"paddle"` trong `RUNNERS`

- [ ] **Step 1: Viết test (đánh dấu slow — cần GPU)**

`apps/model-host/tests/test_paddle_runner.py`:
```python
import pytest

from model_host.runners.paddle import PaddleOcrRunner
from model_host.spec import ModelSpec
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.ocr import RawOcrOutput

pytestmark = pytest.mark.slow

SPEC = ModelSpec(
    id="paddleocr-v4-vi", task=Task.OCR, kind=ModelKind.OPENSOURCE,
    runner="paddle", vram_mb=2500, params={"lang": "vi", "use_angle_cls": True},
)


@pytest.fixture(scope="module")
def runner() -> PaddleOcrRunner:
    r = PaddleOcrRunner()
    r.load(SPEC)
    yield r
    r.unload()


def test_predict_returns_raw_ocr_output(runner, tmp_path_factory):
    image_path = tmp_path_factory.mktemp("img") / "sample.png"
    _write_sample_image(image_path, "HOA DON")
    output = runner.predict(image_path.read_bytes(), SPEC.params)
    assert isinstance(output, RawOcrOutput)
    assert len(output.boxes) >= 1
    assert all(len(b.polygon) >= 4 for b in output.boxes)
    assert "HOA DON" in " ".join(b.text for b in output.boxes).upper()


def _write_sample_image(path, text: str) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(image).text((20, 40), text, fill="black")
    image.save(path)
```

Thêm `"pillow>=10.4"` vào `[dependency-groups] dev` của `pyproject.toml` gốc.

- [ ] **Step 2: Viết paddle.py**

`apps/model-host/src/model_host/runners/paddle.py`:
```python
import io

from model_host.spec import ModelSpec
from vypq_contracts.common import Task
from vypq_contracts.ocr import RawOcrOutput, TextBox


class PaddleOcrRunner:
    task = Task.OCR

    def __init__(self) -> None:
        self._engine = None

    def load(self, spec: ModelSpec) -> None:
        try:
            # Import muộn: chỉ máy GPU mới có gói này, module vẫn phải import
            # được ở mọi nơi để registry liệt kê được model.
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "thiếu extra 'gpu': chạy `uv sync --extra gpu` trên máy có CUDA. "
                "Trên máy dev không GPU, dùng runner 'fake' trong models.dev.yaml."
            ) from exc

        self._engine = PaddleOCR(
            lang=spec.params.get("lang", "vi"),
            use_angle_cls=spec.params.get("use_angle_cls", True),
            show_log=False,
        )

    def unload(self) -> None:
        self._engine = None

    def predict(self, data: bytes, params: dict) -> RawOcrOutput:
        import numpy as np
        from PIL import Image

        image = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
        raw = self._engine.ocr(image, cls=params.get("use_angle_cls", True))
        lines = raw[0] if raw and raw[0] else []
        boxes = [
            TextBox(
                id=index,
                polygon=[(float(x), float(y)) for x, y in polygon],
                text=text,
                confidence=float(confidence),
            )
            for index, (polygon, (text, confidence)) in enumerate(lines)
        ]
        return RawOcrOutput(boxes=boxes)
```

- [ ] **Step 3: Đăng ký runner**

`apps/model-host/src/model_host/runners/__init__.py`:
```python
from model_host.runners.fake import FakeAsrRunner, FakeOcrRunner

RUNNERS: dict[str, type] = {
    "fake": FakeOcrRunner,
    "fake-asr": FakeAsrRunner,
}


def _register_optional() -> None:
    """Đăng ký các runner thật.

    Chúng LUÔN được đăng ký, kể cả khi thư viện ML vắng mặt: import nặng nằm
    trong `load()` nên module này import được ở mọi máy. Đó là chủ ý — thiếu thư
    viện thì `load()` ném, registry cô lập model đó, đánh dấu unavailable và trả
    503 rõ ràng, trong khi các model khác chạy bình thường. Nếu ngược lại, không
    đăng ký runner, thì `acquire()` trả 500 "không biết runner", lặp lại mãi và
    không bao giờ đánh dấu unavailable — tệ hơn hẳn.

    `try/except ImportError` dưới đây chỉ phòng trường hợp chính file runner
    hỏng (ví dụ ai đó thêm import nặng lên top level).
    """
    try:
        from model_host.runners.paddle import PaddleOcrRunner
    except ImportError:
        return
    RUNNERS["paddle"] = PaddleOcrRunner


_register_optional()
```

- [ ] **Step 4: Viết Dockerfile và compose cho máy GPU**

`apps/model-host/Dockerfile`:
```dockerfile
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

# KHÔNG apt-get install python3.12: Ubuntu 22.04 chỉ có python3.10 trong repo
# mặc định nên lệnh đó làm hỏng build. Để uv tự tải CPython 3.12 theo
# .python-version — cùng đúng phiên bản đang chạy ở máy dev.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY packages ./packages
COPY apps/model-host ./apps/model-host
# Kèm cả nhóm dev để chạy được test chậm ngay trên máy GPU (bước 7). Bản build
# thuần production thì thêm --no-dev cho ảnh gọn hơn.
RUN uv sync --frozen --package model-host --extra gpu --group dev

ENV VYPQ_MODELS_PATH=/app/apps/model-host/models.yaml \
    VYPQ_PORT=9000
EXPOSE 9000
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:9000/health || exit 1
CMD ["uv", "run", "uvicorn", "model_host.main:app", "--host", "0.0.0.0", "--port", "9000"]
```

Thêm vào `apps/model-host/pyproject.toml`:
```toml
[project.optional-dependencies]
# Chặn trần paddleocr ở 3.0: bản 3.x đổi .ocr() thành .predict() với shape kết quả
# khác hẳn, `uv lock --upgrade` sẽ âm thầm làm hỏng predict() nếu không khoá.
gpu = ["paddleocr>=2.9,<3", "paddlepaddle-gpu>=2.6", "pillow>=10.4", "numpy>=1.26"]
```

`apps/model-host/docker-compose.yml` — chạy trên máy GPU thuê, một container mỗi GPU:
```yaml
services:
  model-host-0:
    build: {context: ../.., dockerfile: apps/model-host/Dockerfile}
    environment:
      CUDA_VISIBLE_DEVICES: "0"
      VYPQ_HOST_NAME: gpu-0
      VYPQ_TOKEN: ${VYPQ_TOKEN:?bat buoc dat VYPQ_TOKEN}
    ports: ["9001:9000"]
    deploy:
      resources:
        reservations:
          # device_ids chứ không phải count: all — mỗi container phải thấy đúng
          # một GPU. Nhân bản service này cho GPU thứ hai thì đổi thành ["1"].
          devices: [{driver: nvidia, device_ids: ["0"], capabilities: [gpu]}]

  ngrok:
    image: ngrok/ngrok:latest
    command: http model-host-0:9000
    environment:
      NGROK_AUTHTOKEN: ${NGROK_AUTHTOKEN:?bat buoc dat NGROK_AUTHTOKEN}
    # Chỉ mở inspector cho localhost: cổng 4040 không có xác thực và hiện toàn bộ
    # nội dung request đi qua tunnel — mở ra ngoài trên máy thuê là phát không
    # ảnh và kết quả OCR cho bất kỳ ai quét cổng.
    ports: ["127.0.0.1:4040:4040"]
    depends_on: [model-host-0]
```

- [ ] **Step 5: Thêm test cho đường thiếu thư viện (chạy được trên máy không GPU)**

`apps/model-host/tests/test_missing_ml_lib.py`:
```python
import pytest

from model_host.registry import ModelRegistry
from model_host.runners import RUNNERS
from model_host.spec import HostConfig, ModelSpec
from vypq_contracts.common import ModelKind, Task
from vypq_core.errors import ServiceError


def _spec(mid: str, runner: str) -> ModelSpec:
    return ModelSpec(
        id=mid, task=Task.OCR, kind=ModelKind.OPENSOURCE, runner=runner, vram_mb=100
    )


def test_paddle_runner_is_registered_even_without_the_library():
    # Đăng ký luôn là chủ ý: nhờ vậy lỗi thiếu thư viện đi qua đường cô lập của
    # registry (503 + unavailable) thay vì đường "không biết runner" (500, lặp mãi).
    assert "paddle" in RUNNERS


def test_missing_library_isolates_one_model_and_says_how_to_fix_it():
    pytest.importorskip  # noqa: B018 - chỉ để rõ ý: test này chạy KHI paddleocr vắng mặt
    try:
        import paddleocr  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("máy này có paddleocr, đường lỗi không tái hiện được")

    config = HostConfig(
        host_name="gpu-1",
        vram_budget_mb=5000,
        models=[_spec("p", "paddle"), _spec("f", "fake")],
    )
    registry = ModelRegistry(config, runners=RUNNERS)

    with pytest.raises(ServiceError) as exc:
        registry.acquire("p")
    assert exc.value.http_status == 503
    assert "uv sync --extra gpu" in exc.value.message   # phải nói cách sửa

    registry.acquire("f")                                # model khác không bị vạ lây
    assert {i.id: i.available for i in registry.infos()} == {"p": False, "f": True}
```

- [ ] **Step 6: Chạy test nhanh xác nhận không vỡ gì**

Chạy: `uv run pytest apps/model-host -v`
Mong đợi: 23 PASS, 1 deselected (test paddle bị loại vì marker `slow`)

- [ ] **Step 7: Chạy test paddle trên máy GPU**

```bash
docker compose -f apps/model-host/docker-compose.yml up -d --build
docker compose -f apps/model-host/docker-compose.yml exec model-host-0 \
  uv run pytest apps/model-host/tests/test_paddle_runner.py -m slow -v
curl -s localhost:4040/api/tunnels | grep -o 'https://[a-z0-9-]*\.ngrok[^"]*' | head -1
```
Mong đợi: 1 PASS, và lệnh cuối in ra URL ngrok công khai của host.

- [ ] **Step 8: Commit**

```bash
git add apps/model-host
git commit -m "feat(model-host): runner PaddleOCR, Dockerfile CUDA và compose một container mỗi GPU"
```

---
### Task 10: services/ocr — pipeline pre/post-process

Toàn bộ task này là hàm thuần, không mạng, không model. Đây là nơi quyết định chất lượng
OCR ngang với bản thân model, nên phải có test chặt.

**Files:**
- Create: `services/ocr/pyproject.toml`
- Create: `services/ocr/src/ocr_service/__init__.py`
- Create: `services/ocr/src/ocr_service/pipeline/{__init__,preprocess,postprocess}.py`
  (`settings.py` thuộc Task 11, không tạo ở đây)
- Test: `services/ocr/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `vypq_contracts.ocr.{TextBox, RawOcrOutput, OcrResult}`
- Produces:
  - `PreparedImage(data: bytes, scale: float, width: int, height: int)`
  - `prepare_image(data: bytes, max_side: int = 2000) -> PreparedImage`
  - `rescale_boxes(boxes: list[TextBox], factor: float) -> list[TextBox]`
  - `group_lines(boxes: list[TextBox]) -> list[list[TextBox]]` — nguồn gom dòng duy nhất
  - `sort_reading_order(boxes: list[TextBox]) -> list[TextBox]`
  - `text_from_lines(lines: list[list[TextBox]]) -> str`
  - `build_full_text(boxes: list[TextBox]) -> str`
  - `normalize_text(text: str) -> str` — NFC
  - `to_result(raw: RawOcrOutput, scale: float) -> OcrResult`

- [ ] **Step 1: Tạo pyproject cho service ocr**

`services/ocr/pyproject.toml`:
```toml
[project]
name = "ocr-service"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "vypq-contracts",
    "vypq-core",
    "vypq-events",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "python-multipart>=0.0.12",
    "pillow>=10.4",
    "pyyaml>=6.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ocr_service"]

[tool.uv.sources]
vypq-contracts = { workspace = true }
vypq-core = { workspace = true }
vypq-events = { workspace = true }
```

Đăng ký vào root `pyproject.toml`: thêm `"ocr-service",` trước `# <<< workspace members`
và `ocr-service = { workspace = true }` trước `# <<< workspace sources`, rồi `uv sync`.

- [ ] **Step 2: Viết test trước**

`services/ocr/tests/test_pipeline.py`:
```python
import io
import unicodedata

from PIL import Image

import pytest

from ocr_service.pipeline.postprocess import (
    build_full_text,
    group_lines,
    normalize_text,
    rescale_boxes,
    sort_reading_order,
    text_from_lines,
    to_result,
)
from ocr_service.pipeline.preprocess import prepare_image
from vypq_contracts.ocr import RawOcrOutput, TextBox
from vypq_core.errors import ServiceError


def _box(id_: int, x: float, y: float, w: float = 50, h: float = 20, text: str = "x") -> TextBox:
    return TextBox(
        id=id_, polygon=[(x, y), (x + w, y), (x + w, y + h), (x, y + h)], text=text
    )


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_prepare_image_keeps_small_image_unchanged():
    prepared = prepare_image(_png(800, 600), max_side=2000)
    assert prepared.scale == 1.0
    assert (prepared.width, prepared.height) == (800, 600)


def test_prepare_image_shrinks_long_side_to_max():
    prepared = prepare_image(_png(4000, 1000), max_side=2000)
    assert prepared.scale == 0.5
    assert (prepared.width, prepared.height) == (2000, 500)
    assert Image.open(io.BytesIO(prepared.data)).size == (2000, 500)


def test_rescale_boxes_maps_coordinates_back_to_original():
    boxes = [_box(0, 100, 200, w=50, h=20)]
    scaled = rescale_boxes(boxes, 2.0)
    assert scaled[0].polygon[0] == (200.0, 400.0)
    assert scaled[0].polygon[2] == (300.0, 440.0)


def test_rescale_preserves_text_and_confidence():
    box = TextBox(
        id=0, polygon=[(0, 0), (1, 0), (1, 1), (0, 1)], text="ế", confidence=0.5, ignore=True
    )
    out = rescale_boxes([box], 3.0)[0]
    assert (out.text, out.confidence, out.ignore) == ("ế", 0.5, True)


def test_sort_reading_order_groups_boxes_on_the_same_line():
    boxes = [
        _box(0, 300, 10, text="ba"),
        _box(1, 10, 12, text="mot"),
        _box(2, 150, 11, text="hai"),
    ]
    assert [b.text for b in sort_reading_order(boxes)] == ["mot", "hai", "ba"]


def test_sort_reading_order_orders_lines_top_to_bottom():
    boxes = [
        _box(0, 10, 100, text="duoi"),
        _box(1, 10, 10, text="tren"),
    ]
    assert [b.text for b in sort_reading_order(boxes)] == ["tren", "duoi"]


def test_sort_reading_order_tolerates_slight_vertical_jitter():
    # Cùng dòng nhưng lệch vài pixel — không được tách thành hai dòng.
    boxes = [
        _box(0, 200, 14, text="sau"),
        _box(1, 10, 10, text="truoc"),
    ]
    assert [b.text for b in sort_reading_order(boxes)] == ["truoc", "sau"]


def test_build_full_text_joins_lines_with_newline_and_words_with_space():
    boxes = [
        _box(0, 10, 10, text="CONG TY"),
        _box(1, 200, 11, text="ABC"),
        _box(2, 10, 100, text="HOA DON"),
    ]
    assert build_full_text(sort_reading_order(boxes)) == "CONG TY ABC\nHOA DON"


def test_build_full_text_skips_ignored_boxes():
    boxes = [_box(0, 10, 10, text="giu"), _box(1, 200, 10, text="bo")]
    boxes[1].ignore = True
    assert build_full_text(sort_reading_order(boxes)) == "giu"


def test_normalize_text_converts_decomposed_vietnamese_to_nfc():
    decomposed = unicodedata.normalize("NFD", "Hóa đơn tiếng Việt")
    assert decomposed != "Hóa đơn tiếng Việt"
    assert normalize_text(decomposed) == "Hóa đơn tiếng Việt"
    assert unicodedata.is_normalized("NFC", normalize_text(decomposed))


def test_to_result_rescales_sorts_and_normalizes_in_one_pass():
    raw = RawOcrOutput(
        boxes=[
            _box(0, 100, 5, text=unicodedata.normalize("NFD", "đơn")),
            _box(1, 10, 6, text=unicodedata.normalize("NFD", "hóa")),
        ]
    )
    result = to_result(raw, scale=0.5)
    assert result.full_text == "hóa đơn"
    assert unicodedata.is_normalized("NFC", result.full_text)
    assert result.boxes[0].polygon[0] == (20.0, 12.0)   # 10 / 0.5


def test_full_text_never_disagrees_with_box_order_on_jittered_text():
    # Chữ hơi nghiêng: box trên cùng và box trái nhất của một dòng là hai box khác
    # nhau. Trước khi gom dòng về một nguồn, hai hàm ngắt dòng khác nhau ở đây.
    boxes = [_box(0, 200, 0, text="B"), _box(1, 400, 8, text="C"),
             _box(2, 10, 11, text="A"), _box(3, 250, 14, text="D")]
    lines = group_lines(boxes)
    ordered = sort_reading_order(boxes)

    assert ordered == [b for line in lines for b in line]
    assert build_full_text(ordered) == text_from_lines(lines)
    # Số dòng trong full_text bằng số dòng CÓ CHỮ (dòng toàn box ignore bị bỏ).
    visible = [line for line in lines if any(not b.ignore for b in line)]
    assert build_full_text(ordered).count("\n") + 1 == len(visible)


def test_a_large_ignored_stamp_does_not_merge_real_lines():
    # Con dấu mờ cao 200px cạnh chữ cao 20px: nếu tolerance tính cả nó thì hai
    # dòng chữ cách nhau 60px bị gộp làm một.
    boxes = [_box(0, 10, 0, text="LineA"), _box(1, 10, 60, text="LineB")]
    for idx, y in ((2, 0), (3, 300)):
        stamp = _box(idx, 400, y, w=200, h=200, text="")
        stamp.ignore = True
        boxes.append(stamp)
    assert build_full_text(sort_reading_order(boxes)) == "LineA\nLineB"


def test_a_fully_ignored_line_is_dropped_without_leaving_a_blank():
    boxes = [_box(0, 10, 0, text="Tren"), _box(1, 10, 60, text=""),
             _box(2, 10, 120, text="Duoi")]
    boxes[1].ignore = True
    assert build_full_text(sort_reading_order(boxes)) == "Tren\nDuoi"


def test_two_column_layout_interleaves_columns_known_limitation():
    # Hạn chế đã biết, cố ý ghim lại để nó là quyết định chứ không phải bất ngờ:
    # gom theo dải ngang nên hai cột bị trộn. Tách cột thuộc phạm vi sau.
    boxes = []
    for row in range(3):
        boxes.append(_box(row * 2, 10, row * 60, text=f"T{row}"))
        boxes.append(_box(row * 2 + 1, 500, row * 60, text=f"P{row}"))
    assert build_full_text(sort_reading_order(boxes)) == "T0 P0\nT1 P1\nT2 P2"


def test_prepare_image_rejects_an_oversized_image():
    # Ảnh nhỏ + ngưỡng thấp: kiểm đúng hành vi mà không dựng ảnh 144 triệu điểm
    # ảnh thật (tốn RAM trong CI và làm Pillow phun DecompressionBombWarning).
    buf = io.BytesIO()
    Image.new("RGB", (2000, 2000), "white").save(buf, format="PNG")
    with pytest.raises(ServiceError) as exc:
        prepare_image(buf.getvalue(), max_side=2000, max_pixels=1_000)
    assert exc.value.http_status == 422
    assert "điểm ảnh" in exc.value.message


def test_to_result_on_empty_output_gives_empty_text():
    result = to_result(RawOcrOutput(boxes=[]), scale=1.0)
    assert result.full_text == ""
    assert result.boxes == []
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Chạy: `uv run pytest services/ocr -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'ocr_service'`

- [ ] **Step 4: Viết preprocess.py**

`services/ocr/src/ocr_service/pipeline/preprocess.py`:
```python
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

from vypq_contracts.common import ErrorCode
from vypq_core.errors import ServiceError


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    scale: float
    width: int
    height: int


def prepare_image(data: bytes, max_side: int = 2000, max_pixels: int = 60_000_000) -> PreparedImage:
    """Xoay theo EXIF và giới hạn cạnh dài. `scale` để postprocess tính ngược toạ độ."""
    try:
        image = Image.open(io.BytesIO(data))
        # Chặn TRƯỚC khi decode: Pillow chỉ tự ném khi vượt 2x MAX_IMAGE_PIXELS,
        # nên một PNG 450KB giãn ra 144 triệu điểm ảnh vẫn lọt qua và ngốn RAM.
        width, height = image.size
        if width * height > max_pixels:
            raise ServiceError(
                ErrorCode.BAD_INPUT,
                f"ảnh {width}x{height} vượt giới hạn {max_pixels} điểm ảnh",
                422,
            )
        image = ImageOps.exif_transpose(image).convert("RGB")
    except ServiceError:
        raise
    except Exception as exc:
        raise ServiceError(ErrorCode.BAD_INPUT, f"không đọc được ảnh: {exc}", 422) from exc

    longest = max(image.size)
    if longest <= max_side:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return PreparedImage(buf.getvalue(), 1.0, image.width, image.height)

    scale = max_side / longest
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)), Image.LANCZOS
    )
    buf = io.BytesIO()
    resized.save(buf, format="PNG")
    return PreparedImage(buf.getvalue(), scale, resized.width, resized.height)
```

- [ ] **Step 5: Viết postprocess.py**

`services/ocr/src/ocr_service/pipeline/postprocess.py`:
```python
import statistics
import unicodedata

from vypq_contracts.ocr import OcrResult, RawOcrOutput, TextBox

_LINE_TOLERANCE_RATIO = 0.6


def normalize_text(text: str) -> str:
    """Tiếng Việt phải về NFC, nếu không CER so với ground truth sẽ sai."""
    return unicodedata.normalize("NFC", text)


def rescale_boxes(boxes: list[TextBox], factor: float) -> list[TextBox]:
    if factor == 1.0:
        return list(boxes)
    return [
        box.model_copy(update={"polygon": [(x * factor, y * factor) for x, y in box.polygon]})
        for box in boxes
    ]


def _y_center(box: TextBox) -> float:
    return sum(y for _x, y in box.polygon) / len(box.polygon)


def _min_x(box: TextBox) -> float:
    return min(x for x, _y in box.polygon)


def _height(box: TextBox) -> float:
    ys = [y for _x, y in box.polygon]
    return max(ys) - min(ys)


def group_lines(boxes: list[TextBox]) -> list[list[TextBox]]:
    """Gom box thành dòng theo tâm y, mỗi dòng sắp trái sang phải.

    NGUỒN DUY NHẤT quyết định đâu là một dòng. Trước đây `sort_reading_order` và
    `build_full_text` mỗi hàm tự gom một kiểu: hàm đầu neo vào box TRÊN CÙNG của
    dòng, hàm sau neo vào box TRÁI NHẤT. Với chữ hơi nghiêng — đúng thứ xảy ra khi
    chụp hoá đơn bằng điện thoại — hai mốc đó khác nhau, nên `full_text` ngắt dòng
    một đằng còn thứ tự `boxes` một nẻo. Kết quả đọc vẫn xuôi tai nhưng chấm CER
    thì sai, và model bị đổ oan.

    Hạn chế đã biết: thuật toán này gom theo dải ngang, nên tài liệu HAI CỘT sẽ bị
    trộn xen kẽ trái–phải từng dòng. Với hoá đơn một cột thì đúng; bố cục hai cột
    cần tách cột trước (XY-cut) — chưa làm ở Plan A, xem test đánh dấu bên dưới.
    """
    if not boxes:
        return []
    # Đo tolerance trên chữ THẬT, nhưng vẫn gom cả box bị bỏ qua vào dòng. Nếu
    # tính median trên tất cả, một con dấu mờ cao 200px giữa các dòng chữ cao 20px
    # sẽ kéo median lên 110, tolerance lên 66, và hai dòng chữ cách nhau 60px bị
    # gộp làm một — im lặng, không lỗi, đúng loại tài liệu hệ thống này phục vụ.
    measured = [b for b in boxes if not b.ignore] or boxes
    tolerance = statistics.median(_height(b) for b in measured) * _LINE_TOLERANCE_RATIO
    lines: list[list[TextBox]] = []
    for box in sorted(boxes, key=_y_center):
        if lines and abs(_y_center(box) - _y_center(lines[-1][0])) <= tolerance:
            lines[-1].append(box)
        else:
            lines.append([box])
    return [sorted(line, key=_min_x) for line in lines]


def sort_reading_order(boxes: list[TextBox]) -> list[TextBox]:
    return [box for line in group_lines(boxes) for box in line]


def text_from_lines(lines: list[list[TextBox]]) -> str:
    """Ghép theo dòng: cùng dòng nối bằng dấu cách, khác dòng xuống hàng.

    Dòng chỉ toàn box `ignore` bị bỏ hẳn thay vì để lại dòng trống — vùng không
    đọc được không nên biến thành một dòng rỗng trong transcript. Hệ quả:
    số dòng của `full_text` bằng số dòng CÓ CHỮ, không phải `len(lines)`.
    """
    rendered = [
        " ".join(box.text for box in line if not box.ignore) for line in lines
    ]
    return normalize_text("\n".join(line for line in rendered if line))


def build_full_text(boxes: list[TextBox]) -> str:
    return text_from_lines(group_lines(boxes))


def to_result(raw: RawOcrOutput, scale: float) -> OcrResult:
    factor = 1.0 / scale if scale else 1.0
    boxes = rescale_boxes(raw.boxes, factor)
    boxes = [b.model_copy(update={"text": normalize_text(b.text)}) for b in boxes]
    # Gom dòng đúng MỘT lần rồi dùng chung cho cả hai đầu ra: thứ tự box và
    # full_text không thể lệch nhau nữa vì chúng sinh ra từ cùng một kết quả.
    lines = group_lines(boxes)
    return OcrResult(
        full_text=text_from_lines(lines),
        boxes=[box for line in lines for box in line],
    )
```

`services/ocr/src/ocr_service/pipeline/__init__.py` và `services/ocr/src/ocr_service/__init__.py`:
```python
__all__: list[str] = []
```

- [ ] **Step 6: Chạy test để xác nhận pass**

Chạy: `uv run pytest services/ocr -v`
Mong đợi: 12 PASS

- [ ] **Step 7: Commit**

```bash
git add services/ocr
git commit -m "feat(ocr): pipeline pre/post-process, sắp thứ tự đọc và chuẩn hoá NFC"
```

---

### Task 11: services/ocr — backend, handler, HTTP entrypoint

**Files:**
- Create: `services/ocr/config.yaml`, `services/ocr/service.yaml`, `services/ocr/Dockerfile`
- Create: `services/ocr/src/ocr_service/settings.py`
- Create: `services/ocr/src/ocr_service/backend/{__init__,base,remote,fake}.py`
- Create: `services/ocr/src/ocr_service/{handler,main}.py`
- Test: `services/ocr/tests/{test_backend_remote,test_handler,test_api}.py`

**Interfaces:**
- Consumes: `vypq_core.host_registry.{HostRef, StaticHostRegistry}`, `vypq_core.http_client.UpstreamClient`, `vypq_core.breaker.CircuitBreaker`, pipeline từ Task 10
- Produces:
  - `OcrBackend` Protocol: `await infer(image: bytes, model_id: str) -> RawOcrOutput`
  - `FakeOcrBackend(output: RawOcrOutput | None = None, error: Exception | None = None)` — có `.calls: list[tuple[bytes, str]]`
  - `RemoteOcrBackend(registry, *, timeout_s=60.0, max_attempts=3, failure_threshold=5, recovery_timeout_s=30.0, sleep=asyncio.sleep, jitter=random.random)` — có `.infer()`, `.infer_uri()`, `.open_circuits()`, `.aclose()`
  - `OcrHandler(backend, *, default_model: str, max_side: int = 2000)` — `await run(image: bytes, model_version: str | None, trace_id: str) -> OcrResponse`
  - `OcrSettings(default_model, max_side, timeout_s, hosts_path)`
  - `build_app() -> FastAPI` với `POST /v1/ocr` (multipart)

- [ ] **Step 1: Viết test cho backend remote**

`services/ocr/tests/test_backend_remote.py`:
```python
import httpx
import pytest
import respx

from ocr_service.backend.remote import RemoteOcrBackend
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.hosting import ModelInfo
from vypq_core.breaker import CircuitOpenError
from vypq_core.host_registry import HostRef, NoHostAvailableError, StaticHostRegistry
from vypq_core.http_client import UpstreamError

HOST_A = "http://gpu-a:9000"
HOST_B = "http://gpu-b:9000"

OK_BODY = {
    "model_id": "m1",
    "task": "ocr",
    "output": {"boxes": [
        {"id": 0, "polygon": [[0, 0], [10, 0], [10, 5], [0, 5]], "text": "A"}
    ]},
    "timing": {"load_ms": 0, "infer_ms": 7},
}


def _host(name: str, url: str) -> HostRef:
    return HostRef(
        name=name, url=url, token="tk",
        models=[ModelInfo(id="m1", task=Task.OCR, kind=ModelKind.OPENSOURCE, runner="paddle")],
    )


async def _noop_sleep(_s: float) -> None:
    return None


def _backend(hosts: list[HostRef], **kw) -> RemoteOcrBackend:
    return RemoteOcrBackend(
        StaticHostRegistry(hosts), sleep=_noop_sleep, jitter=lambda: 0.0, **kw
    )


@respx.mock
async def test_infer_posts_multipart_and_parses_boxes():
    route = respx.post(f"{HOST_A}/v1/infer/upload").mock(
        return_value=httpx.Response(200, json=OK_BODY)
    )
    backend = _backend([_host("a", HOST_A)])
    output = await backend.infer(b"\xff\xd8jpeg", "m1")
    assert output.boxes[0].text == "A"
    assert route.called
    assert b"multipart/form-data" in route.calls[0].request.headers["content-type"].encode()


@respx.mock
async def test_infer_sends_bearer_token_of_the_chosen_host():
    captured: dict[str, str] = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=OK_BODY)

    respx.post(f"{HOST_A}/v1/infer/upload").mock(side_effect=_record)
    await _backend([_host("a", HOST_A)]).infer(b"x", "m1")
    assert captured["auth"] == "Bearer tk"


@respx.mock
async def test_infer_uri_posts_json_instead_of_multipart():
    # Đường uri có sẵn cho Plan B (khi máy GPU cùng mạng với MinIO); Plan A dùng inline.
    route = respx.post(f"{HOST_A}/v1/infer").mock(return_value=httpx.Response(200, json=OK_BODY))
    backend = _backend([_host("a", HOST_A)])
    await backend.infer_uri("https://minio/a.jpg", "m1")
    assert route.called
    assert route.calls[0].request.headers["content-type"] == "application/json"


async def test_unknown_model_raises_no_host_available():
    with pytest.raises(NoHostAvailableError):
        await _backend([_host("a", HOST_A)]).infer(b"x", "khong-co")


@respx.mock
async def test_breaker_is_shared_across_calls_to_the_same_host():
    # Nếu mỗi lần gọi lại tạo client mới, breaker sẽ reset và không bao giờ mở.
    respx.post(f"{HOST_A}/v1/infer/upload").mock(side_effect=httpx.ConnectError("chết"))
    backend = _backend([_host("a", HOST_A)], max_attempts=1, failure_threshold=2)
    for _ in range(2):
        with pytest.raises(UpstreamError):
            await backend.infer(b"x", "m1")
    with pytest.raises(CircuitOpenError):
        await backend.infer(b"x", "m1")


@respx.mock
async def test_each_host_has_its_own_breaker():
    respx.post(f"{HOST_A}/v1/infer/upload").mock(side_effect=httpx.ConnectError("chết"))
    respx.post(f"{HOST_B}/v1/infer/upload").mock(return_value=httpx.Response(200, json=OK_BODY))
    hosts = [_host("a", HOST_A), _host("b", HOST_B)]
    backend = _backend(hosts, max_attempts=1, failure_threshold=1)
    with pytest.raises(UpstreamError):
        await backend.infer(b"x", "m1")
    hosts[0].healthy = False
    output = await backend.infer(b"x", "m1")
    assert output.boxes[0].text == "A"


@respx.mock
async def test_client_is_rebuilt_when_the_host_changes_its_url():
    # Máy thuê lại: cùng tên host, URL ngrok mới. Cache theo tên thôi sẽ gửi
    # request tới tunnel cũ đã chết mãi mãi.
    old = respx.post(f"{HOST_A}/v1/infer/upload").mock(return_value=httpx.Response(200, json=OK_BODY))
    new = respx.post(f"{HOST_B}/v1/infer/upload").mock(return_value=httpx.Response(200, json=OK_BODY))
    hosts = [_host("gpu-1", HOST_A)]
    backend = _backend(hosts)

    await backend.infer(b"x", "m1")
    assert old.called and not new.called

    hosts[0].url = HOST_B                      # thuê lại, URL mới
    await backend.infer(b"x", "m1")
    assert new.called
    await backend.aclose()


@respx.mock
async def test_inflight_returns_to_zero_after_failure():
    respx.post(f"{HOST_A}/v1/infer/upload").mock(side_effect=httpx.ConnectError("chết"))
    hosts = [_host("a", HOST_A)]
    backend = _backend(hosts, max_attempts=1)
    with pytest.raises(UpstreamError):
        await backend.infer(b"x", "m1")
    assert hosts[0].inflight == 0
```

- [ ] **Step 2: Viết test cho handler và API**

`services/ocr/tests/test_handler.py`:
```python
import io

import pytest
from PIL import Image

from ocr_service.backend.fake import FakeOcrBackend
from ocr_service.handler import OcrHandler
from vypq_contracts.ocr import RawOcrOutput, TextBox
from vypq_core.errors import ServiceError


def _png(width: int = 800, height: int = 600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def _raw(*texts: str) -> RawOcrOutput:
    return RawOcrOutput(
        boxes=[
            TextBox(
                id=i,
                polygon=[(10, 10 + i * 40), (100, 10 + i * 40), (100, 40 + i * 40), (10, 40 + i * 40)],
                text=t,
            )
            for i, t in enumerate(texts)
        ]
    )


async def test_run_returns_response_with_full_text():
    handler = OcrHandler(FakeOcrBackend(_raw("dòng một", "dòng hai")), default_model="m1")
    resp = await handler.run(_png(), model_version=None, trace_id="t1")
    assert resp.result.full_text == "dòng một\ndòng hai"
    assert resp.trace_id == "t1"
    assert resp.model_version == "m1"
    assert resp.latency_ms >= 0


async def test_run_uses_requested_model_version():
    backend = FakeOcrBackend(_raw("a"))
    handler = OcrHandler(backend, default_model="m1")
    resp = await handler.run(_png(), model_version="m2", trace_id="t1")
    assert resp.model_version == "m2"
    assert backend.calls[0][1] == "m2"


async def test_run_rescales_boxes_when_image_is_downsized():
    handler = OcrHandler(FakeOcrBackend(_raw("a")), default_model="m1", max_side=100)
    resp = await handler.run(_png(400, 200), model_version=None, trace_id="t1")
    # Ảnh bị thu 4 lần → toạ độ trả về phải nhân ngược lại 4.
    assert resp.result.boxes[0].polygon[0] == (40.0, 40.0)


async def test_run_rejects_non_image_input():
    handler = OcrHandler(FakeOcrBackend(_raw("a")), default_model="m1")
    with pytest.raises(ServiceError) as exc:
        await handler.run(b"day-khong-phai-anh", model_version=None, trace_id="t1")
    assert exc.value.http_status == 422


async def test_backend_error_propagates_unchanged():
    boom = RuntimeError("gpu chết")
    handler = OcrHandler(FakeOcrBackend(error=boom), default_model="m1")
    with pytest.raises(RuntimeError):
        await handler.run(_png(), model_version=None, trace_id="t1")
```

`services/ocr/tests/test_api.py`:
```python
import io

import httpx
from PIL import Image

from ocr_service.backend.fake import FakeOcrBackend
from ocr_service.handler import OcrHandler
from ocr_service.main import build_app_with
from ocr_service.settings import OcrSettings
from vypq_contracts.ocr import RawOcrOutput, TextBox


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buf, format="PNG")
    return buf.getvalue()


def _app(backend):
    settings = OcrSettings(service_name="ocr", default_model="m1")
    return build_app_with(OcrHandler(backend, default_model=settings.default_model), settings)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_post_ocr_returns_result():
    raw = RawOcrOutput(
        boxes=[TextBox(id=0, polygon=[(0, 0), (9, 0), (9, 9), (0, 9)], text="HÓA ĐƠN")]
    )
    async with _client(_app(FakeOcrBackend(raw))) as c:
        resp = await c.post("/v1/ocr", files={"file": ("a.png", _png(), "image/png")})
    body = resp.json()
    assert resp.status_code == 200
    assert body["result"]["full_text"] == "HÓA ĐƠN"
    assert body["model_version"] == "m1"


async def test_post_ocr_with_broken_file_returns_422_envelope():
    async with _client(_app(FakeOcrBackend(RawOcrOutput()))) as c:
        resp = await c.post("/v1/ocr", files={"file": ("a.png", b"rac", "image/png")})
    assert resp.status_code == 422
    assert resp.json()["code"] == "bad_input"


async def test_ready_reports_degraded_when_a_host_circuit_is_open():
    class _OpenBackend(FakeOcrBackend):
        def open_circuits(self) -> list[str]:
            return ["gpu-1"]

    settings = OcrSettings(service_name="ocr", default_model="m1")
    backend = _OpenBackend(RawOcrOutput())
    app = build_app_with(
        OcrHandler(backend, default_model=settings.default_model), settings, backend=backend
    )
    async with _client(app) as c:
        resp = await c.get("/ready")
    assert resp.status_code == 503
    assert "gpu-1" in resp.json()["detail"]["model_host"]


async def test_trace_id_header_is_echoed_back():
    async with _client(_app(FakeOcrBackend(RawOcrOutput()))) as c:
        resp = await c.post(
            "/v1/ocr",
            files={"file": ("a.png", _png(), "image/png")},
            headers={"x-trace-id": "trace-42"},
        )
    assert resp.headers["x-trace-id"] == "trace-42"
    assert resp.json()["trace_id"] == "trace-42"
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Chạy: `uv run pytest services/ocr -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'ocr_service.backend'`

- [ ] **Step 4: Viết backend base và fake**

`services/ocr/src/ocr_service/backend/base.py`:
```python
from typing import Protocol

from vypq_contracts.ocr import RawOcrOutput


class OcrBackend(Protocol):
    async def infer(self, image: bytes, model_id: str) -> RawOcrOutput: ...
```

`services/ocr/src/ocr_service/backend/fake.py`:
```python
from vypq_contracts.ocr import RawOcrOutput


class FakeOcrBackend:
    """Backend không cần mạng, không cần GPU. Lý do chính khiến backend là interface."""

    def __init__(
        self, output: RawOcrOutput | None = None, error: Exception | None = None
    ) -> None:
        self._output = output or RawOcrOutput()
        self._error = error
        self.calls: list[tuple[bytes, str]] = []

    async def infer(self, image: bytes, model_id: str) -> RawOcrOutput:
        self.calls.append((image, model_id))
        if self._error is not None:
            raise self._error
        return self._output
```

- [ ] **Step 5: Viết backend remote**

`services/ocr/src/ocr_service/backend/remote.py`:
```python
import asyncio
import random
from collections.abc import Awaitable, Callable

from vypq_contracts.common import ErrorCode
from vypq_contracts.hosting import InferRequest, InferResponse
from vypq_contracts.ocr import RawOcrOutput
from vypq_core.breaker import CircuitBreaker
from vypq_core.errors import ServiceError
from vypq_core.host_registry import HostRef, StaticHostRegistry
from vypq_core.http_client import UpstreamClient


class RemoteOcrBackend:
    """Gọi model-host qua HTTP. Giữ một UpstreamClient cho mỗi host để circuit
    breaker sống xuyên suốt các lần gọi — tạo client mới mỗi lần sẽ reset breaker
    và nó không bao giờ mở được."""

    def __init__(
        self,
        registry: StaticHostRegistry,
        *,
        timeout_s: float = 60.0,
        max_attempts: int = 3,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._registry = registry
        self._timeout_s = timeout_s
        self._max_attempts = max_attempts
        self._failure_threshold = failure_threshold
        self._recovery_timeout_s = recovery_timeout_s
        self._sleep = sleep
        self._jitter = jitter
        # tên host -> ((url, token), client). Xem _client_for để biết vì sao khoá kép.
        self._clients: dict[str, tuple[tuple[str, str | None], UpstreamClient]] = {}

    async def _client_for(self, host: HostRef) -> UpstreamClient:
        # Khoá cache theo (url, token) chứ không chỉ theo tên: máy GPU thuê lại
        # giữ nguyên tên nhưng ĐỔI URL ngrok mỗi lần thuê. Nhớ theo tên thôi là
        # ghim service vào tunnel đã chết, không có đường tự khỏi ngoài restart.
        key = (host.url, host.token)
        cached = self._clients.get(host.name)
        if cached is not None and cached[0] != key:
            await cached[1].aclose()
            cached = None
        if cached is None:
            cached = (
                key,
                UpstreamClient(
                    host.url,
                    token=host.token,
                    timeout_s=self._timeout_s,
                    max_attempts=self._max_attempts,
                    breaker=CircuitBreaker(
                        failure_threshold=self._failure_threshold,
                        recovery_timeout_s=self._recovery_timeout_s,
                    ),
                    sleep=self._sleep,
                    jitter=self._jitter,
                ),
            )
            self._clients[host.name] = cached
        return cached[1]

    async def infer(self, image: bytes, model_id: str) -> RawOcrOutput:
        # Thứ tự bắt buộc: pick() -> lease() -> mọi thứ khác. `inflight` chỉ tăng
        # lúc vào lease, nên bất kỳ await nào chen giữa pick và lease đều cho các
        # coroutine khác đọc lại con số cũ và dồn hết vào cùng một host.
        # _client_for() có await (đóng client cũ khi host đổi URL) nên phải nằm
        # TRONG lease, không phải trước.
        host = await self._registry.pick(model_id)
        async with self._registry.lease(host):
            client = await self._client_for(host)
            response = await client.request(
                "POST",
                "/v1/infer/upload",
                data={"model_id": model_id},
                files={"file": ("input", image, "application/octet-stream")},
            )
        return self._parse(response.json())

    async def infer_uri(self, uri: str, model_id: str) -> RawOcrOutput:
        host = await self._registry.pick(model_id)
        payload = InferRequest(model_id=model_id, input_uri=uri)
        async with self._registry.lease(host):
            client = await self._client_for(host)
            response = await client.request(
                "POST", "/v1/infer", json=payload.model_dump(mode="json")
            )
        return self._parse(response.json())

    @staticmethod
    def _parse(body: dict) -> RawOcrOutput:
        parsed = InferResponse.model_validate(body)
        if not isinstance(parsed.output, RawOcrOutput):
            # assert sẽ bị python -O gỡ bỏ; đây là dữ liệu từ máy khác nên phải
            # kiểm thật và báo lỗi rõ thay vì AssertionError rơi vào handler 500.
            raise ServiceError(
                ErrorCode.UPSTREAM_ERROR,
                f"model-host trả output kiểu {type(parsed.output).__name__} cho task ocr",
                http_status=502,
            )
        return parsed.output

    def open_circuits(self) -> list[str]:
        """Tên các host đang bị circuit chặn — dùng cho /ready."""
        return [n for n, (_key, c) in self._clients.items() if c.breaker.is_open()]

    async def aclose(self) -> None:
        for _key, client in self._clients.values():
            await client.aclose()
        self._clients.clear()
```

- [ ] **Step 6: Viết settings, handler, main**

`services/ocr/src/ocr_service/settings.py`:
```python
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from vypq_core.config import BaseServiceSettings
from vypq_core.host_registry import HostRef


class OcrSettings(BaseServiceSettings):
    service_name: str = "ocr"
    port: int = 8001
    default_model: str = "paddleocr-v4-vi"
    max_side: int = 2000
    timeout_s: float = 60.0
    hosts_path: Path = Path("config.yaml")


class HostDiscovery(BaseModel):
    source: str = "static"
    url: str | None = None
    refresh_s: int = 15
    fallback_static: list[HostRef] = Field(default_factory=list)


class HostsFile(BaseModel):
    host_discovery: HostDiscovery = Field(default_factory=HostDiscovery)


def load_hosts(path: Path) -> list[HostRef]:
    """Plan A chỉ đọc fallback_static. Plan B thêm nhánh source == 'gateway'."""
    if not path.is_file():
        return []
    parsed = HostsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return parsed.host_discovery.fallback_static
```

`services/ocr/src/ocr_service/handler.py`:
```python
import time

from ocr_service.backend.base import OcrBackend
from ocr_service.pipeline.postprocess import to_result
from ocr_service.pipeline.preprocess import prepare_image
from vypq_contracts.ocr import OcrResponse


class OcrHandler:
    """Logic dùng chung cho cả HTTP lẫn Kafka worker."""

    def __init__(self, backend: OcrBackend, *, default_model: str, max_side: int = 2000) -> None:
        self._backend = backend
        self._default_model = default_model
        self._max_side = max_side

    async def run(
        self, image: bytes, model_version: str | None, trace_id: str
    ) -> OcrResponse:
        model_id = model_version or self._default_model
        started = time.monotonic()
        prepared = prepare_image(image, max_side=self._max_side)
        raw = await self._backend.infer(prepared.data, model_id)
        result = to_result(raw, prepared.scale)
        return OcrResponse(
            trace_id=trace_id,
            model_version=model_id,
            result=result,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
```

`services/ocr/src/ocr_service/main.py`:
```python
from contextlib import asynccontextmanager

from fastapi import APIRouter, File, Form, Request, UploadFile

from ocr_service.backend.remote import RemoteOcrBackend
from ocr_service.handler import OcrHandler
from ocr_service.settings import OcrSettings, load_hosts
from vypq_contracts.common import HealthStatus
from vypq_contracts.ocr import OcrResponse
from vypq_core.app import create_app
from vypq_core.host_registry import StaticHostRegistry
from vypq_core.logging import get_trace_id


def build_app_with(handler: OcrHandler, settings: OcrSettings, backend=None, lifespan=None):
    router = APIRouter(prefix="/v1")

    @router.post("/ocr", response_model=OcrResponse)
    async def ocr(
        request: Request,
        file: UploadFile = File(...),
        model_version: str | None = Form(default=None),
    ) -> OcrResponse:
        trace_id = request.headers.get("x-trace-id") or get_trace_id()
        return await handler.run(await file.read(), model_version, trace_id)

    async def _upstream_ready() -> tuple[HealthStatus, str]:
        if backend is None:
            return HealthStatus.OK, "fake backend"
        open_hosts = backend.open_circuits()
        if open_hosts:
            return HealthStatus.DOWN, f"circuit đang mở: {', '.join(open_hosts)}"
        return HealthStatus.OK, "model-host phản hồi bình thường"

    return create_app(
        settings, routers=[router], readiness={"model_host": _upstream_ready}, lifespan=lifespan
    )


def build_app():
    settings = OcrSettings()
    registry = StaticHostRegistry(load_hosts(settings.hosts_path))
    backend = RemoteOcrBackend(registry, timeout_s=settings.timeout_s)
    handler = OcrHandler(
        backend, default_model=settings.default_model, max_side=settings.max_side
    )

    @asynccontextmanager
    async def _lifespan(_app):
        yield
        # Không đóng thì các connection httpx của mỗi host treo tới khi tiến trình
        # chết — với worker chạy dài (Task 12) đó là rò tài nguyên thật.
        await backend.aclose()

    return build_app_with(handler, settings, backend=backend, lifespan=_lifespan)


app = build_app()
```

`services/ocr/src/ocr_service/backend/__init__.py`:
```python
__all__: list[str] = []
```

- [ ] **Step 7: Viết config.yaml và service.yaml**

`services/ocr/config.yaml` — dùng đúng shape mà spec mục 3.3 quy định, để bước 8 (Plan B)
chỉ phải đổi `source: static` thành `source: gateway`, không phải viết lại file:
```yaml
host_discovery:
  source: static              # Plan B đổi thành: gateway
  url: http://gateway:8080/v1/hosts
  refresh_s: 15
  fallback_static:
    - name: gpu-1
      url: https://doi-url-ngrok-tai-day.ngrok.app
      token: ${VYPQ_MODEL_HOST_TOKEN}
      models:
        - {id: paddleocr-v4-vi, task: ocr, kind: opensource, runner: paddle}
```

`services/ocr/service.yaml` — `name` là SLUG chứ không phải task: hai service cùng
task (ví dụ `ocr` và `ocr-handwriting`) phải có tên khác nhau, nếu không chúng
trùng nhau trong registry của gateway. Topic thì đúng là theo task.
```yaml
name: ocr
port: 8001
capability: {input: image, output: text_boxes}
consumes: [infer.ocr.requests]
produces: [infer.ocr.results]
```

- [ ] **Step 8: Chạy toàn bộ test service ocr**

Chạy: `uv run pytest services/ocr -v`
Mong đợi: 17 + 8 + 5 + 4 = 34 PASS

- [ ] **Step 9: Chạy thử end-to-end với model-host fake**

```bash
# cửa sổ 1: model-host chế độ fake
cd apps/model-host && VYPQ_TOKEN=sekret VYPQ_MODELS_PATH=models.dev.yaml \
  uv run uvicorn model_host.main:app --port 9001 &   # models.dev.yaml đã có sẵn trong repo

# cửa sổ 2: ocr service trỏ vào đó
cd services/ocr
cat > config.dev.yaml <<'YAML'
host_discovery:
  source: static
  fallback_static:
    - name: gpu-dev
      url: http://localhost:9001
      token: sekret
      models: [{id: fake-ocr, task: ocr, kind: opensource, runner: fake}]
YAML
VYPQ_HOSTS_PATH=config.dev.yaml VYPQ_DEFAULT_MODEL=fake-ocr \
  uv run uvicorn ocr_service.main:app --port 8001 &
sleep 3
uv run python -c "
from PIL import Image; Image.new('RGB',(300,200),'white').save('/tmp/a.png')"
curl -s -F file=@/tmp/a.png localhost:8001/v1/ocr | head -c 400
```
Mong đợi: JSON có `full_text` là `"XIN CHÀO\nthế giới"`.

- [ ] **Step 10: Commit**

```bash
git add services/ocr
git commit -m "feat(ocr): backend remote/fake, handler dùng chung và HTTP entrypoint"
```

---
### Task 12: services/ocr — Kafka worker

**Files:**
- Create: `services/ocr/src/ocr_service/worker.py`
- Modify: `services/ocr/src/ocr_service/settings.py` (thêm `brokers`, `model_version`, `group_prefix`)
- Test: `services/ocr/tests/test_worker.py`

**Interfaces:**
- Consumes: `vypq_events.consumer.EventConsumer`, `vypq_events.producer.EventProducer`, `OcrHandler` từ Task 11
- Produces:
  - `group_id(prefix: str, model_version: str | None) -> str`
  - `OcrWorkerHandler(handler: OcrHandler, producer, *, forced_model: str | None, fetch)` — `await __call__(envelope: RawEnvelope) -> None`
  - `build_worker() -> EventConsumer`

- [ ] **Step 1: Viết test trước**

`services/ocr/tests/test_worker.py`:
```python
import io

import pytest
from PIL import Image

from ocr_service.backend.fake import FakeOcrBackend
from ocr_service.handler import OcrHandler
from ocr_service.worker import OcrWorkerHandler, group_id
from vypq_contracts.common import Task
from vypq_contracts.ocr import RawOcrOutput, TextBox
from vypq_core.errors import ServiceError
from vypq_core.http_client import UpstreamError
from vypq_events.envelope import EventEnvelope, RawEnvelope
from vypq_events.schemas.inference import InferenceRequested


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buf, format="PNG")
    return buf.getvalue()


def _raw() -> RawOcrOutput:
    return RawOcrOutput(
        boxes=[TextBox(id=0, polygon=[(0, 0), (9, 0), (9, 9), (0, 9)], text="HÓA ĐƠN")]
    )


def _envelope(model_version: str | None = None) -> RawEnvelope:
    env = EventEnvelope[InferenceRequested].new(
        "inference.requested",
        InferenceRequested(
            task=Task.OCR,
            input_uri="https://minio/a.png",
            model_version=model_version,
            eval_job_id="e1",
            dataset_item_id="item-7",
        ),
    )
    return RawEnvelope.model_validate_json(env.model_dump_json())


class FakeProducer:
    def __init__(self) -> None:
        self.published: list[tuple] = []

    async def publish(self, topic, envelope, key=None):
        self.published.append((topic, envelope, key))


async def _fetch(_uri: str) -> bytes:
    return _png()


def test_group_id_is_default_when_no_model_version_forced():
    assert group_id("ocr", None) == "ocr-default"


def test_group_id_includes_forced_model_version():
    # Mỗi model version một consumer group → cùng event được mọi model xử lý.
    assert group_id("ocr", "vietocr-ft-invoice") == "ocr-vietocr-ft-invoice"


async def test_worker_publishes_completed_event_to_result_topic():
    producer = FakeProducer()
    worker = OcrWorkerHandler(
        OcrHandler(FakeOcrBackend(_raw()), default_model="m1"),
        producer,
        forced_model=None,
        fetch=_fetch,
    )
    envelope = _envelope()
    await worker(envelope)

    topic, published, key = producer.published[0]
    assert topic == "infer.ocr.results"
    assert key == envelope.trace_id
    assert published.payload.model_version == "m1"
    assert published.payload.output["full_text"] == "HÓA ĐƠN"
    assert published.payload.eval_job_id == "e1"
    assert published.payload.dataset_item_id == "item-7"
    assert published.trace_id == envelope.trace_id


async def test_event_model_version_is_used_when_nothing_is_forced():
    backend = FakeOcrBackend(_raw())
    worker = OcrWorkerHandler(
        OcrHandler(backend, default_model="m1"), FakeProducer(), forced_model=None, fetch=_fetch
    )
    await worker(_envelope(model_version="m2"))
    assert backend.calls[0][1] == "m2"


async def test_forced_model_overrides_the_event_field():
    backend = FakeOcrBackend(_raw())
    worker = OcrWorkerHandler(
        OcrHandler(backend, default_model="m1"),
        FakeProducer(),
        forced_model="vietocr-ft",
        fetch=_fetch,
    )
    await worker(_envelope(model_version="m2"))
    assert backend.calls[0][1] == "vietocr-ft"


async def test_upstream_error_is_not_swallowed():
    # Worker phải để lỗi bay lên EventConsumer, nếu không consumer sẽ không
    # bao giờ biết mà pause — và message sẽ rơi vào DLQ.
    worker = OcrWorkerHandler(
        OcrHandler(FakeOcrBackend(error=UpstreamError("gpu chết")), default_model="m1"),
        FakeProducer(),
        forced_model=None,
        fetch=_fetch,
    )
    with pytest.raises(UpstreamError):
        await worker(_envelope())


async def test_input_fetch_connection_error_is_retryable_not_dead_letter():
    # Kho đối tượng chập chờn KHÔNG được làm cả hàng đợi rơi vào DLQ.
    import httpx
    import respx

    from ocr_service.worker import fetch_bytes

    with respx.mock:
        respx.get("http://minio/a.png").mock(side_effect=httpx.ConnectError("mat ket noi"))
        with pytest.raises(UpstreamError):
            await fetch_bytes("http://minio/a.png")


async def test_input_fetch_500_is_retryable():
    import httpx
    import respx

    from ocr_service.worker import fetch_bytes

    with respx.mock:
        respx.get("http://minio/a.png").mock(return_value=httpx.Response(503))
        with pytest.raises(UpstreamError):
            await fetch_bytes("http://minio/a.png")


async def test_input_fetch_404_is_permanent_and_goes_to_dlq():
    # URI trỏ vào chỗ không tồn tại là dữ liệu hỏng thật, retry mãi vẫn hỏng.
    import httpx
    import respx

    from ocr_service.worker import fetch_bytes

    with respx.mock:
        respx.get("http://minio/a.png").mock(return_value=httpx.Response(404))
        with pytest.raises(ServiceError) as exc:
            await fetch_bytes("http://minio/a.png")
    assert not isinstance(exc.value, UpstreamError)


async def test_nothing_is_published_when_inference_fails():
    producer = FakeProducer()
    worker = OcrWorkerHandler(
        OcrHandler(FakeOcrBackend(error=UpstreamError("gpu chết")), default_model="m1"),
        producer,
        forced_model=None,
        fetch=_fetch,
    )
    with pytest.raises(UpstreamError):
        await worker(_envelope())
    assert producer.published == []
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest services/ocr/tests/test_worker.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'ocr_service.worker'`

- [ ] **Step 3: Bổ sung settings cho worker**

Thêm vào `services/ocr/src/ocr_service/settings.py`, trong class `OcrSettings`:
```python
    brokers: str = "localhost:9092"
    group_prefix: str = "ocr"
    model_version: str | None = None   # VYPQ_MODEL_VERSION — đặt để bật shadow-run
```

- [ ] **Step 4: Viết worker.py**

`services/ocr/src/ocr_service/worker.py`:
```python
import asyncio
from collections.abc import Awaitable, Callable

import httpx

from ocr_service.backend.remote import RemoteOcrBackend
from ocr_service.handler import OcrHandler
from ocr_service.settings import OcrSettings, load_hosts
from vypq_contracts.common import ErrorCode, Task
from vypq_core.errors import ServiceError
from vypq_core.host_registry import StaticHostRegistry
from vypq_core.http_client import UpstreamError
from vypq_core.logging import get_logger, setup_logging
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import EventEnvelope, RawEnvelope
from vypq_events.producer import EventProducer
from vypq_events.schemas.inference import InferenceCompleted, InferenceRequested
from vypq_events.topics import dlq_topic, request_topic, result_topic

log = get_logger(__name__)


def group_id(prefix: str, model_version: str | None) -> str:
    """Không đặt MODEL_VERSION → group mặc định. Có đặt → group riêng cho model đó,
    nên cùng một event được mọi model version đang bật xử lý (shadow-run)."""
    return f"{prefix}-{model_version}" if model_version else f"{prefix}-default"


async def fetch_bytes(uri: str) -> bytes:
    """Tải input, PHÂN LOẠI ĐÚNG lỗi tải.

    httpx trần ném ConnectError/TimeoutException — những lỗi này không phải
    UpstreamError nên EventConsumer coi là dữ liệu hỏng và dead-letter ngay.
    Hậu quả đo được: MinIO/R2 chập chờn vài giây là cả hàng đợi rơi vào DLQ,
    dù chẳng có gì sai với dữ liệu. Kết nối hỏng và 5xx là sự cố hạ tầng →
    UpstreamError → consumer dừng chờ. Chỉ 4xx mới thật sự là URI hỏng.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(uri)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise UpstreamError(f"không tải được {uri}: {exc}") from exc
    if response.status_code >= 500:
        raise UpstreamError(f"{uri} trả {response.status_code}")
    if response.status_code >= 400:
        raise ServiceError(
            ErrorCode.BAD_INPUT, f"{uri} trả {response.status_code}", http_status=422
        )
    return response.content


class OcrWorkerHandler:
    def __init__(
        self,
        handler: OcrHandler,
        producer,
        *,
        forced_model: str | None,
        fetch: Callable[[str], Awaitable[bytes]] = fetch_bytes,
    ) -> None:
        self._handler = handler
        self._producer = producer
        self._forced_model = forced_model
        self._fetch = fetch

    async def __call__(self, envelope: RawEnvelope) -> None:
        request = InferenceRequested.model_validate(envelope.payload)
        image = await self._fetch(request.input_uri)
        # Lỗi upstream ở đây cố ý bay lên EventConsumer để nó pause thay vì DLQ.
        response = await self._handler.run(
            image,
            self._forced_model or request.model_version,
            envelope.trace_id,
        )
        completed = InferenceCompleted(
            task=Task.OCR,
            model_version=response.model_version,
            input_uri=request.input_uri,
            output=response.result.model_dump(mode="json"),
            latency_ms=response.latency_ms,
            eval_job_id=request.eval_job_id,
            dataset_item_id=request.dataset_item_id,
        )
        await self._producer.publish(
            result_topic(Task.OCR),
            EventEnvelope[InferenceCompleted].new(
                "inference.completed", completed, trace_id=envelope.trace_id
            ),
            key=envelope.trace_id,
        )


async def main() -> None:
    settings = OcrSettings()
    setup_logging(settings.log_level)
    registry = StaticHostRegistry(load_hosts(settings.hosts_path))
    backend = RemoteOcrBackend(registry, timeout_s=settings.timeout_s)
    handler = OcrHandler(
        backend, default_model=settings.default_model, max_side=settings.max_side
    )
    producer = EventProducer(settings.brokers)
    await producer.start()

    consumer = EventConsumer(
        topic=request_topic(Task.OCR),
        group_id=group_id(settings.group_prefix, settings.model_version),
        handler=OcrWorkerHandler(handler, producer, forced_model=settings.model_version),
        dlq_topic=dlq_topic(Task.OCR),
        producer=producer,
        brokers=settings.brokers,
    )
    await consumer.start()
    log.info("worker_started", group=group_id(settings.group_prefix, settings.model_version))
    try:
        await consumer.run()
    finally:
        await consumer.stop()
        await producer.stop()
        await backend.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Chạy: `uv run pytest services/ocr -v`
Mong đợi: 34 + 10 = 44 PASS

- [ ] **Step 6: Viết Dockerfile cho service**

`services/ocr/Dockerfile`:
```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl libgl1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services/ocr ./services/ocr
RUN uv sync --frozen --package ocr-service

ENV VYPQ_PORT=8001 VYPQ_HOSTS_PATH=/app/services/ocr/config.yaml
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:8001/health || exit 1
CMD ["uv", "run", "uvicorn", "ocr_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

- [ ] **Step 7: Kiểm chứng thủ công — worker pause khi model-host chết**

Đây là hành vi quan trọng nhất của Plan A, phải xem tận mắt.

```bash
docker compose -f infra/compose/docker-compose.dev.yml up -d redpanda
cd apps/model-host && VYPQ_TOKEN=sekret VYPQ_MODELS_PATH=models.dev.yaml \
  uv run uvicorn model_host.main:app --port 9001 &
cd services/ocr && VYPQ_HOSTS_PATH=config.dev.yaml VYPQ_DEFAULT_MODEL=fake-ocr \
  uv run python -m ocr_service.worker &

# Phải là ẢNH THẬT. Nếu input_uri trỏ vào JSON (ví dụ /health), prepare_image()
# ở PHÍA SERVICE từ chối ngay với BAD_INPUT — lỗi vĩnh viễn, vào DLQ lập tức,
# không bao giờ chạm tới đường pause. Kịch bản sẽ không chứng minh được gì cả.
uv run python -c "from PIL import Image; Image.new('RGB',(300,200),'white').save('/tmp/e2e.png')"
(cd /tmp && uv run python -m http.server 8899 >/dev/null 2>&1 &)
sleep 1

# đẩy 5 event vào topic
uv run python - <<'PY'
import asyncio
from vypq_contracts.common import Task
from vypq_events.envelope import EventEnvelope
from vypq_events.producer import EventProducer
from vypq_events.schemas.inference import InferenceRequested
from vypq_events.topics import request_topic

async def main():
    p = EventProducer("localhost:9092"); await p.start()
    for i in range(5):
        env = EventEnvelope[InferenceRequested].new(
            "inference.requested",
            InferenceRequested(task=Task.OCR, input_uri="http://localhost:8899/e2e.png"))
        await p.publish(request_topic(Task.OCR), env)
    await p.stop()
asyncio.run(main())
PY

# giết model-host giữa chừng rồi xem log worker
pkill -f "model_host.main:app"
```

Mong đợi trong log worker: dòng `retry_exhausted_pausing` rồi `consumer_paused`, và
**không có** dòng `event_dead_lettered`. Kiểm luôn topic DLQ cho chắc:
`docker exec compose-redpanda-1 rpk topic consume infer.ocr.dlq -o start -n 10`
Bật lại model-host → xuất hiện `consumer_resumed` và các event còn lại được xử lý tiếp.
Kiểm tra topic DLQ rỗng tại http://localhost:8090 (Redpanda Console).

- [ ] **Step 8: Commit**

```bash
git add services/ocr
git commit -m "feat(ocr): kafka worker, consumer group theo model version cho shadow-run"
```

---

### Task 13: Template và script sinh service mới

**Files:**
- Create: `services/_template/` (bản sao rút gọn của `services/ocr`, đổi tên bằng token)
- Create: `scripts/new-service.sh`
- Test: `tests/test_new_service_script.py`

**Interfaces:**
- Consumes: cấu trúc `services/ocr` từ Task 10–12
- Produces: `scripts/new-service.sh <slug> <task>` sinh ra `services/<slug>/` chạy được, test pass ngay

Token thay thế trong template — **phải phủ cả tên kiểu**, không chỉ tên gói. Template được
chép từ `services/ocr` nên còn dính `RawOcrOutput`, `OcrResponse`, `vypq_contracts.ocr`; bỏ sót
thì service `asr` sinh ra sẽ import sai kiểu:

| Token | Với `asr` | Với `ocr` |
|---|---|---|
| `__SLUG__` | `asr` | `ocr` | ← tên service, KHÁC task khi có nhiều service cùng task |
| `__PKG__` | `asr_service` | `ocr_service` |
| `__TASK__` | `asr` | `ocr` |
| `__TASKUPPER__` | `ASR` | `OCR` |
| `__RAWOUT__` | `RawAsrOutput` | `RawOcrOutput` |
| `__RESP__` | `AsrResponse` | `OcrResponse` |
| `__BACKEND__` | `AsrBackend` | `OcrBackend` |
| `__HANDLER__` | `AsrHandler` | `OcrHandler` |
| `__PORT__` | `8002` | `8001` |

- [ ] **Step 1: Viết test trước**

`tests/test_new_service_script.py`:
```python
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "new-service.sh"


@pytest.fixture
def generated():
    target = REPO / "services" / "tmptest"
    root_pyproject = REPO / "pyproject.toml"
    original = root_pyproject.read_text(encoding="utf-8")
    if target.exists():
        shutil.rmtree(target)
    yield target
    if target.exists():
        shutil.rmtree(target)
    # Script sửa root pyproject — trả lại nguyên trạng để không rác workspace.
    root_pyproject.write_text(original, encoding="utf-8")


def test_script_generates_a_service_that_passes_its_own_tests(generated):
    subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, check=True, capture_output=True
    )
    assert (generated / "src" / "tmptest_service" / "handler.py").is_file()
    assert (generated / "src" / "tmptest_service" / "worker.py").is_file()
    assert (generated / "service.yaml").is_file()

    result = subprocess.run(
        ["uv", "run", "pytest", f"services/tmptest", "-q"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_script_leaves_no_unreplaced_tokens(generated):
    subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, check=True, capture_output=True
    )
    for path in generated.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in (
                "__SLUG__", "__PKG__", "__TASK__", "__TASKUPPER__",
                "__RAWOUT__", "__RESP__", "__BACKEND__", "__HANDLER__", "__PORT__",
            ):
                assert token not in text, f"{path} còn sót {token}"


def test_script_registers_the_new_service_in_the_workspace_root(generated):
    subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, check=True, capture_output=True
    )
    root = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert '"tmptest-service",' in root
    assert "tmptest-service = { workspace = true }" in root
    # Đăng ký rồi thì venv phải import được gói mới.
    result = subprocess.run(
        ["uv", "run", "python", "-c", "import tmptest_service"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_script_refuses_to_overwrite_existing_service(generated):
    subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, check=True, capture_output=True
    )
    result = subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "đã tồn tại" in result.stderr
```

- [ ] **Step 2: Tạo template từ service ocr**

```bash
mkdir -p services/_template/src/__PKG__/{backend,pipeline} services/_template/tests
cp services/ocr/src/ocr_service/backend/{base,fake}.py services/_template/src/__PKG__/backend/
cp services/ocr/src/ocr_service/backend/remote.py services/_template/src/__PKG__/backend/
cp services/ocr/src/ocr_service/{handler,main,worker,settings}.py services/_template/src/__PKG__/
cp services/ocr/src/ocr_service/pipeline/__init__.py services/_template/src/__PKG__/pipeline/
cp services/ocr/{pyproject.toml,service.yaml,config.yaml,Dockerfile} services/_template/
cp services/ocr/tests/test_handler.py services/_template/tests/
```

Sau đó thay mọi chuỗi cố định bằng token (`sed -i ''` là cú pháp BSD trên macOS):
```bash
cd services/_template
find . -type f -print0 | while IFS= read -r -d '' f; do
  sed -i '' \
    -e 's/ocr_service/__PKG__/g' \
    -e 's/ocr-service/__SLUG__-service/g' \
    -e 's/vypq_contracts\.ocr/vypq_contracts.__TASK__/g' \
    -e 's/RawOcrOutput/__RAWOUT__/g' \
    -e 's/OcrResponse/__RESP__/g' \
    -e 's/OcrBackend/__BACKEND__/g' \
    -e 's/OcrHandler/__HANDLER__/g' \
    -e 's/Task\.OCR/Task.__TASKUPPER__/g' \
    -e 's/8001/__PORT__/g' \
    "$f"
done
touch src/__PKG__/__init__.py src/__PKG__/backend/__init__.py
# Kiểm tra không còn sót chữ 'ocr' viết thường hay 'Ocr' viết hoa nào:
! grep -rn 'ocr\|Ocr\|OCR' . --include='*.py' --include='*.toml' --include='*.yaml'
```

Thay `services/_template/tests/test_handler.py` bằng bản trung tính — bản chép từ OCR dùng
PIL và ảnh PNG, không dùng được cho service audio:
```python
import pytest

from __PKG__.backend.fake import Fake__BACKEND__
from __PKG__.handler import __HANDLER__
from vypq_contracts.__TASK__ import __RAWOUT__


async def test_run_returns_response_with_default_model():
    handler = __HANDLER__(Fake__BACKEND__(__RAWOUT__()), default_model="m1")
    response = await handler.run(b"payload", model_version=None, trace_id="t1")
    assert response.model_version == "m1"
    assert response.trace_id == "t1"
    assert response.latency_ms >= 0


async def test_run_uses_requested_model_version():
    backend = Fake__BACKEND__(__RAWOUT__())
    handler = __HANDLER__(backend, default_model="m1")
    response = await handler.run(b"payload", model_version="m2", trace_id="t1")
    assert response.model_version == "m2"
    assert backend.calls[0][1] == "m2"


async def test_backend_error_propagates_unchanged():
    handler = __HANDLER__(Fake__BACKEND__(error=RuntimeError("hỏng")), default_model="m1")
    with pytest.raises(RuntimeError):
        await handler.run(b"payload", model_version=None, trace_id="t1")
```

Template `handler.py` cũng phải trung tính (không có `prepare_image`, không có `scale`) —
service cụ thể tự nối pipeline của mình vào, như Task 14 làm với `asr`:
```python
import time

from __PKG__.backend.base import __BACKEND__
from vypq_contracts.__TASK__ import __RESP__, __RAWOUT__


class __HANDLER__:
    def __init__(self, backend: __BACKEND__, *, default_model: str) -> None:
        self._backend = backend
        self._default_model = default_model

    async def run(self, data: bytes, model_version: str | None, trace_id: str) -> __RESP__:
        model_id = model_version or self._default_model
        started = time.monotonic()
        raw = await self._backend.infer(data, model_id)
        return __RESP__(
            trace_id=trace_id,
            model_version=model_id,
            result=self.to_result(raw),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def to_result(self, raw: __RAWOUT__):
        raise NotImplementedError("service cụ thể phải nối pipeline postprocess của mình")
```

Rút gọn `services/_template/src/__PKG__/pipeline/__init__.py` thành pipeline trung tính:
```python
"""Pipeline mặc định: không biến đổi gì. Service cụ thể tự thay bằng logic của mình."""


def prepare_input(data: bytes, **_kwargs):
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Prepared:
        data: bytes
        scale: float = 1.0

    return Prepared(data=data)
```

- [ ] **Step 3: Viết scripts/new-service.sh**

`scripts/new-service.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "dùng: $0 <slug> <task: ocr|asr> [port]" >&2
  exit 2
fi

SLUG="$1"
TASK="$2"
PORT="${3:-8010}"
PKG="${SLUG}_service"
TASKUPPER="$(echo "$TASK" | tr '[:lower:]' '[:upper:]')"
TITLE="$(echo "${TASK:0:1}" | tr '[:lower:]' '[:upper:]')${TASK:1}"
RAWOUT="Raw${TITLE}Output"
RESP="${TITLE}Response"
BACKEND="${TITLE}Backend"
HANDLER="${TITLE}Handler"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/services/_template"
DST="$ROOT/services/$SLUG"

if [[ -e "$DST" ]]; then
  echo "services/$SLUG đã tồn tại — dừng lại để không ghi đè" >&2
  exit 1
fi

cp -R "$SRC" "$DST"
mv "$DST/src/__PKG__" "$DST/src/$PKG"

find "$DST" -type f -print0 | while IFS= read -r -d '' file; do
  sed -i '' \
    -e "s/__PKG__/$PKG/g" \
    -e "s/__SLUG__/$SLUG/g" \
    -e "s/__TASKUPPER__/$TASKUPPER/g" \
    -e "s/__RAWOUT__/$RAWOUT/g" \
    -e "s/__RESP__/$RESP/g" \
    -e "s/__BACKEND__/$BACKEND/g" \
    -e "s/__HANDLER__/$HANDLER/g" \
    -e "s/__TASK__/$TASK/g" \
    -e "s/__PORT__/$PORT/g" \
    "$file"
done

# Đăng ký member mới vào workspace root, nếu không venv sẽ không có gói này.
if ! grep -q "\"$SLUG-service\"" "$ROOT/pyproject.toml"; then
  sed -i '' \
    -e "s|^    # <<< workspace members\$|    \"$SLUG-service\",\n    # <<< workspace members|" \
    -e "s|^# <<< workspace sources\$|$SLUG-service = { workspace = true }\n# <<< workspace sources|" \
    "$ROOT/pyproject.toml"
fi
uv sync --project "$ROOT" >/dev/null

# Thứ tự import phụ thuộc tên task (vypq_contracts.$TASK sắp xen giữa các import
# khác), nên template không thể có sẵn thứ tự đúng cho mọi tên. Để ruff tự sắp.
uv run --project "$ROOT" ruff check --fix "$DST" >/dev/null 2>&1 || true

echo "đã tạo services/$SLUG (task=$TASK, port=$PORT)"
echo "bước tiếp: viết pipeline và runner tương ứng, rồi chạy: uv run pytest services/$SLUG"
```

```bash
chmod +x scripts/new-service.sh
```

- [ ] **Step 4: Chạy test script**

Chạy: `uv run pytest tests/test_new_service_script.py -v`
Mong đợi: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add services/_template scripts tests
git commit -m "feat(template): khung service và script sinh service mới"
```

---

### Task 14: services/asr và runner Whisper

**Files:**
- Create: `services/asr/` (sinh bằng `scripts/new-service.sh`)
- Create: `services/asr/src/asr_service/pipeline/postprocess.py`
- Modify: `services/asr/src/asr_service/handler.py`
- Create: `apps/model-host/src/model_host/runners/whisper.py`
- Modify: `apps/model-host/src/model_host/runners/__init__.py`
- Test: `services/asr/tests/test_pipeline.py`, `apps/model-host/tests/test_whisper_runner.py`

**Interfaces:**
- Consumes: template từ Task 13, `RawAsrOutput`/`AsrResult`/`Segment` từ Task 2
- Produces:
  - `merge_segments(segments: list[Segment], gap_s: float = 0.3) -> list[Segment]`
  - `build_transcript(segments: list[Segment]) -> str` — chuẩn hoá NFC
  - `to_result(raw: RawAsrOutput) -> AsrResult`
  - `WhisperRunner` đăng ký dưới khoá `"whisper"` trong `RUNNERS`

- [ ] **Step 1: Sinh service asr từ template**

```bash
./scripts/new-service.sh asr asr 8002
uv run pytest services/asr -q
```
Mong đợi: test sinh kèm PASS ngay, chưa cần sửa gì.

- [ ] **Step 2: Viết test cho pipeline asr**

`services/asr/tests/test_pipeline.py`:
```python
import unicodedata

from asr_service.pipeline.postprocess import build_transcript, merge_segments, to_result
from vypq_contracts.asr import RawAsrOutput, Segment


def _seg(start: float, end: float, text: str, speaker: str | None = None) -> Segment:
    return Segment(start=start, end=end, text=text, speaker=speaker)


def test_merge_joins_segments_separated_by_a_short_gap():
    merged = merge_segments([_seg(0.0, 1.0, "xin"), _seg(1.1, 2.0, "chào")], gap_s=0.3)
    assert len(merged) == 1
    assert merged[0].text == "xin chào"
    assert (merged[0].start, merged[0].end) == (0.0, 2.0)


def test_merge_keeps_segments_separated_by_a_long_gap():
    merged = merge_segments([_seg(0.0, 1.0, "xin"), _seg(5.0, 6.0, "chào")], gap_s=0.3)
    assert len(merged) == 2


def test_merge_never_joins_across_different_speakers():
    merged = merge_segments(
        [_seg(0.0, 1.0, "xin", "A"), _seg(1.1, 2.0, "chào", "B")], gap_s=0.3
    )
    assert len(merged) == 2


def test_merge_sorts_out_of_order_segments_before_joining():
    # Đoạn tới sai thứ tự thời gian: hiệu ra số âm, lọt ngưỡng, sinh đoạn end < start.
    merged = merge_segments([_seg(5.0, 6.0, "sau"), _seg(0.0, 1.0, "truoc")])
    assert [s.text for s in merged] == ["truoc", "sau"]
    assert all(s.end >= s.start for s in merged)


def test_merge_never_produces_a_segment_ending_before_it_starts():
    merged = merge_segments(
        [_seg(2.0, 3.0, "b"), _seg(0.0, 1.0, "a"), _seg(1.1, 1.9, "giua")]
    )
    assert all(s.end >= s.start for s in merged)
    assert " ".join(s.text for s in merged).split() == ["a", "giua", "b"]


def test_merge_on_empty_input_returns_empty():
    assert merge_segments([]) == []


def test_build_transcript_joins_with_single_space_and_normalizes_nfc():
    decomposed = unicodedata.normalize("NFD", "tiếng Việt")
    transcript = build_transcript([_seg(0.0, 1.0, "xin chào"), _seg(1.2, 2.0, decomposed)])
    assert transcript == "xin chào tiếng Việt"
    assert unicodedata.is_normalized("NFC", transcript)


def test_to_result_merges_then_builds_text():
    raw = RawAsrOutput(segments=[_seg(0.0, 1.0, "xin"), _seg(1.1, 2.0, "chào")])
    result = to_result(raw)
    assert result.text == "xin chào"
    assert len(result.segments) == 1
```

- [ ] **Step 3: Viết postprocess.py cho asr**

`services/asr/src/asr_service/pipeline/postprocess.py`:
```python
import unicodedata

from vypq_contracts.asr import AsrResult, RawAsrOutput, Segment


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def merge_segments(segments: list[Segment], gap_s: float = 0.3) -> list[Segment]:
    """Gộp các đoạn liền nhau của cùng một người nói, cách nhau dưới `gap_s` giây.

    Sắp theo `start` trước khi gộp: nếu đoạn tới không đúng thứ tự thời gian —
    diarization nhiều luồng, hoặc kết quả gộp từ nhiều kênh — thì hiệu
    `segment.start - previous.end` ra số âm và vẫn lọt qua ngưỡng, sinh ra đoạn
    có `end < start` và chữ đảo ngược. Không lỗi, không cảnh báo.
    """
    merged: list[Segment] = []
    for segment in sorted(segments, key=lambda s: s.start):
        previous = merged[-1] if merged else None
        joinable = (
            previous is not None
            and previous.speaker == segment.speaker
            and 0 <= segment.start - previous.end <= gap_s
        )
        if joinable:
            merged[-1] = previous.model_copy(
                update={"end": segment.end, "text": f"{previous.text} {segment.text}".strip()}
            )
        else:
            merged.append(segment)
    return merged


def build_transcript(segments: list[Segment]) -> str:
    return normalize_text(" ".join(s.text for s in segments if s.text).strip())


def to_result(raw: RawAsrOutput) -> AsrResult:
    segments = [
        s.model_copy(update={"text": normalize_text(s.text)})
        for s in merge_segments(raw.segments)
    ]
    return AsrResult(text=build_transcript(segments), segments=segments)
```

- [ ] **Step 4: Nối postprocess vào handler asr**

Sửa `services/asr/src/asr_service/handler.py` — thay thân hàm `run`:
```python
import time

from asr_service.backend.base import AsrBackend
from asr_service.pipeline.postprocess import to_result
from vypq_contracts.asr import AsrResponse


class AsrHandler:
    def __init__(self, backend: AsrBackend, *, default_model: str) -> None:
        self._backend = backend
        self._default_model = default_model

    async def run(
        self, audio: bytes, model_version: str | None, trace_id: str
    ) -> AsrResponse:
        model_id = model_version or self._default_model
        started = time.monotonic()
        # Audio không cần resize như ảnh — gửi nguyên bytes sang model-host.
        raw = await self._backend.infer(audio, model_id)
        return AsrResponse(
            trace_id=trace_id,
            model_version=model_id,
            result=to_result(raw),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
```

- [ ] **Step 5: Chạy test asr**

Chạy: `uv run pytest services/asr -v`
Mong đợi: 8 test pipeline + các test sinh từ template, tất cả PASS

- [ ] **Step 6: Viết runner Whisper**

`apps/model-host/src/model_host/runners/whisper.py`:
```python
import io

from model_host.spec import ModelSpec
from vypq_contracts.asr import RawAsrOutput, Segment
from vypq_contracts.common import Task


class WhisperRunner:
    task = Task.ASR

    def __init__(self) -> None:
        self._model = None

    def load(self, spec: ModelSpec) -> None:
        from faster_whisper import WhisperModel  # import muộn: chỉ máy GPU mới có

        self._model = WhisperModel(
            spec.source.get("repo", "large-v3"),
            device=spec.params.get("device", "cuda"),
            compute_type=spec.params.get("compute_type", "float16"),
        )

    def unload(self) -> None:
        self._model = None

    def predict(self, data: bytes, params: dict) -> RawAsrOutput:
        segments, _info = self._model.transcribe(
            io.BytesIO(data),
            language=params.get("language", "vi"),
            vad_filter=params.get("vad_filter", True),
        )
        return RawAsrOutput(
            segments=[
                Segment(start=float(s.start), end=float(s.end), text=s.text.strip())
                for s in segments
            ]
        )
```

Cập nhật `_register_optional()` trong `apps/model-host/src/model_host/runners/__init__.py`:
```python
def _register_optional() -> None:
    try:
        from model_host.runners.paddle import PaddleOcrRunner
    except ImportError:
        pass
    else:
        RUNNERS["paddle"] = PaddleOcrRunner

    try:
        from model_host.runners.whisper import WhisperRunner
    except ImportError:
        pass
    else:
        RUNNERS["whisper"] = WhisperRunner
```

Thêm vào `[project.optional-dependencies] gpu` của `apps/model-host/pyproject.toml`:
`"faster-whisper>=1.0"`.

- [ ] **Step 7: Viết test cho WhisperRunner**

`apps/model-host/tests/test_whisper_runner.py`:
```python
import math
import struct
import wave

import pytest

from model_host.runners.whisper import WhisperRunner
from model_host.spec import ModelSpec
from vypq_contracts.asr import RawAsrOutput
from vypq_contracts.common import ModelKind, Task

pytestmark = pytest.mark.slow

SPEC = ModelSpec(
    id="whisper-large-v3", task=Task.ASR, kind=ModelKind.OPENSOURCE, runner="whisper",
    vram_mb=6000, source={"repo": "large-v3"}, params={"language": "vi"},
)


def test_predict_returns_segments_with_increasing_timestamps(tmp_path):
    path = tmp_path / "tone.wav"
    _write_tone(path)
    runner = WhisperRunner()
    runner.load(SPEC)
    try:
        output = runner.predict(path.read_bytes(), SPEC.params)
    finally:
        runner.unload()
    assert isinstance(output, RawAsrOutput)
    for earlier, later in zip(output.segments, output.segments[1:], strict=False):
        assert earlier.end <= later.start


def _write_tone(path, seconds: float = 2.0, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 220 * t / rate)))
            for t in range(int(rate * seconds))
        )
        handle.writeframes(frames)
```

- [ ] **Step 8: Chạy toàn bộ test của Plan A**

Chạy: `uv run pytest -v`
Mong đợi: tất cả PASS, các test `slow` được bỏ qua.

Chạy trên máy GPU: `uv run pytest -m slow -v`
Mong đợi: test paddle và whisper PASS.

- [ ] **Step 9: Commit**

```bash
git add services/asr apps/model-host
git commit -m "feat(asr): service asr sinh từ template và runner Whisper"
```

---

## Hoàn tất Plan A

Sau task 14, kiểm chứng lần cuối bằng `scripts/smoke-test.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
echo "== unit test =="
uv run pytest -q
echo "== lint =="
uv run ruff check .
echo "== model-host lên =="
curl -fsS localhost:9001/v1/models -H "Authorization: Bearer ${VYPQ_TOKEN}" >/dev/null
echo "== không token phải bị 401 =="
[[ "$(curl -s -o /dev/null -w '%{http_code}' localhost:9001/v1/models)" == "401" ]]
echo "== ocr trả kết quả =="
curl -fsS -F file=@tests/fixtures/sample.png localhost:8001/v1/ocr | grep -q full_text
echo "TẤT CẢ ĐẠT"
```

Plan B bắt đầu từ đây: gateway giữ host registry, và service đổi
`host_discovery.source` từ `static` sang `gateway`.
