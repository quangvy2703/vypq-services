# Plan B1 — Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng gateway giữ danh sách máy GPU thuê đang sống, phục vụ danh sách đó cho các service, định tuyến request, và ghi lại mọi lần chạy — để cả nền tảng dùng được bằng `curl` mà chưa cần UI.

**Architecture:** Gateway giữ registry host trong Postgres và **poll ra** từng máy GPU (chiều duy nhất chạy được khi cả hai đầu sau NAT). Service bỏ danh sách host tĩnh, chuyển sang hỏi gateway mỗi 15s qua `DiscoveryHostRegistry` — cùng Protocol với `StaticHostRegistry` của Plan A nên không service nào phải sửa logic. Mọi request đi qua `/v1/invoke` được ghi vào bảng `runs`, cả đường sync lẫn đường Kafka.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, Postgres 16, alembic, httpx, aiokafka, prometheus-client, pytest + aiosqlite.

**Spec:** `docs/superpowers/specs/2026-08-18-vypq-ai-services-platform-design.md`

**Điều kiện tiên quyết:** Plan A đã merge (hoặc nhánh này tách từ `feat/plan-a-nen-tang-service`). Toàn bộ `packages/*`, `apps/model-host`, `services/ocr`, `services/asr` phải có sẵn.

## Global Constraints

- Python **3.12** cố định. System python3 là 3.9 — luôn `uv run`, không gọi `python3`.
- **uv workspace.** Member mới phải đăng ký vào root `pyproject.toml` ở CẢ `[dependency-groups] dev` LẪN `[tool.uv.sources]`, chèn trước hai dòng mốc `# <<< workspace members` và `# <<< workspace sources`. Khai trong `[tool.uv.workspace] members` KHÔNG khiến nó được cài. Gặp `ModuleNotFoundError` dù đã đăng ký đúng thì `uv sync --reinstall-package <tên>`.
- Pydantic **v2**, SQLAlchemy **2.x** kiểu khai báo mới (`Mapped`, `mapped_column`).
- `uv run ruff check .` phải sạch trước mỗi commit.
- **Lệnh test mặc định `uv run pytest` KHÔNG được đòi Docker.** Test repository chạy trên SQLite in-memory; test cần Postgres/Redpanda thật đánh dấu `@pytest.mark.slow`. Hệ quả: **không dùng kiểu cột riêng của Postgres** (`ARRAY`, `JSONB`) — dùng `JSON` và `Text` để cùng một schema chạy được trên cả hai.
- Mọi biến môi trường tiền tố `VYPQ_`, lồng nhau bằng `__`.
- `default_is_retryable` phân loại theo **kiểu exception**, không theo `ErrorCode`. Không được "dọn dẹp" cho nó đọc `ErrorCode` — sẽ lật ngược hai quyết định cố ý ở Plan A và phá bảo đảm không-mất-dữ-liệu.
- Commit sau mỗi task. Conventional Commits prefix tiếng Anh, mô tả tiếng Việt.

## File Structure

| File | Trách nhiệm |
|---|---|
| `apps/gateway/pyproject.toml` | Khai báo package, dependency |
| `apps/gateway/alembic.ini`, `migrations/` | Migration schema |
| `apps/gateway/config/services.yaml` | Danh sách service gateway biết tới |
| `apps/gateway/src/gateway/settings.py` | `GatewaySettings` |
| `apps/gateway/src/gateway/db/engine.py` | Async engine + session factory |
| `apps/gateway/src/gateway/db/models.py` | Bảng `hosts`, `services`, `model_versions`, `runs` |
| `apps/gateway/src/gateway/db/repo.py` | Truy vấn — nơi DUY NHẤT viết SQL |
| `apps/gateway/src/gateway/registry/hosts.py` | `HostStore`: CRUD host |
| `apps/gateway/src/gateway/registry/poller.py` | Vòng poll `/health` + `/v1/models`, ghi `healthy` |
| `apps/gateway/src/gateway/registry/services.py` | `ServiceStore`: đọc config, poll `/v1/info` |
| `apps/gateway/src/gateway/proxy.py` | Đường sync: forward tới service, ghi run |
| `apps/gateway/src/gateway/dispatcher.py` | Đường async: publish Kafka |
| `apps/gateway/src/gateway/result_consumer.py` | Consume `infer.*.results` → bảng `runs` |
| `apps/gateway/src/gateway/api/{hosts,services,invoke,runs}.py` | Router |
| `apps/gateway/src/gateway/main.py` | Entrypoint, lifespan |
| `packages/vypq-core/src/vypq_core/host_registry.py` | Thêm `DiscoveryHostRegistry` |
| `packages/vypq-core/src/vypq_core/service_info.py` | Router `/v1/info` dùng chung |
| `packages/vypq-contracts/src/vypq_contracts/gateway.py` | `HostRegistration`, `HostsResponse`, `ServiceInfo`, `InvokeRequest`, `RunRecord` |
| `infra/prometheus/`, `infra/grafana/` | Cấu hình scrape + alert rule |

---
### Task 1: Contracts cho gateway

**Files:**
- Create: `packages/vypq-contracts/src/vypq_contracts/gateway.py`
- Test: `packages/vypq-contracts/tests/test_gateway_schemas.py`

**Interfaces:**
- Consumes: `vypq_contracts.common.{Task, HealthStatus}`, `vypq_contracts.hosting.ModelInfo`
- Produces:
  - `HostRegistration(name: str, url: str, token: str | None)`
  - `HostState(name, url, healthy: bool, models: list[ModelInfo], last_seen_at: datetime | None, last_error: str | None)`
  - `HostsResponse(hosts: list[HostState])`
  - `ServiceInfo(name: str, task: Task, capability_input: str, capability_output: str, version: str, invoke_path: str, default_model: str | None)`
  - `ServiceState(info: ServiceInfo, base_url: str, status: HealthStatus, last_seen_at: datetime | None)`
  - `ServicesResponse(services: list[ServiceState])`
  - `InvokeMode` (StrEnum: `SYNC="sync"`, `ASYNC="async"`)
  - `InvokeRequest(service: str, model_version: str | None, mode: InvokeMode, input_uri: str | None)`
  - `InvokeResponse(trace_id: str, mode: InvokeMode, run_id: str | None, result: dict | None)`
  - `RunStatus` (StrEnum: `PENDING`, `OK`, `FAILED`)
  - `RunRecord(id, trace_id, service, model_version, mode, status, input_uri, output, latency_ms, error, created_at)`
  - `RunsResponse(runs: list[RunRecord], total: int)`

- [ ] **Step 1: Viết test trước**

`packages/vypq-contracts/tests/test_gateway_schemas.py`:
```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from vypq_contracts.common import HealthStatus, ModelKind, Task
from vypq_contracts.gateway import (
    HostRegistration,
    HostState,
    HostsResponse,
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
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest packages/vypq-contracts/tests/test_gateway_schemas.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'vypq_contracts.gateway'`

- [ ] **Step 3: Viết gateway.py**

`packages/vypq-contracts/src/vypq_contracts/gateway.py`:
```python
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from vypq_contracts.common import HealthStatus, Task
from vypq_contracts.hosting import ModelInfo


class HostRegistration(BaseModel):
    """Thân request khi đăng ký một máy GPU vừa thuê."""

    name: str
    url: str
    token: str | None = None


class HostState(BaseModel):
    """Trạng thái một host như gateway đang thấy.

    KHÔNG mang `token`: gateway giữ token trong DB và cấp riêng cho service qua
    đường khác. Nhét nó vào đây là phát bí mật kèm mọi lần liệt kê host.
    """

    name: str
    url: str
    # Mặc định False: máy vừa đăng ký chưa poll lần nào thì "chưa biết", và
    # chưa biết phải nghiêng về không định tuyến vào.
    healthy: bool = False
    models: list[ModelInfo] = Field(default_factory=list)
    last_seen_at: datetime | None = None
    last_error: str | None = None


class HostsResponse(BaseModel):
    hosts: list[HostState] = Field(default_factory=list)


class ServiceInfo(BaseModel):
    """Service tự mô tả mình — gateway lấy qua GET /v1/info."""

    name: str
    task: Task
    capability_input: str
    capability_output: str
    version: str
    # Đường nhận multipart để chạy inference, ví dụ "/v1/ocr". Service TỰ khai
    # chứ gateway không suy ra từ tên hay task: Plan A hardcode "/v1/ocr", còn
    # service sinh từ template có thể đặt khác. Đoán ở đây là gọi sai đường.
    invoke_path: str
    default_model: str | None = None


class ServiceState(BaseModel):
    info: ServiceInfo
    base_url: str
    status: HealthStatus = HealthStatus.DOWN
    last_seen_at: datetime | None = None


class ServicesResponse(BaseModel):
    services: list[ServiceState] = Field(default_factory=list)


class InvokeMode(StrEnum):
    SYNC = "sync"
    ASYNC = "async"


class InvokeRequest(BaseModel):
    service: str
    model_version: str | None = None
    mode: InvokeMode = InvokeMode.SYNC
    input_uri: str | None = None


class InvokeResponse(BaseModel):
    trace_id: str
    mode: InvokeMode
    run_id: str | None = None
    result: dict[str, Any] | None = None


class RunStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"


class RunRecord(BaseModel):
    id: str
    trace_id: str
    service: str
    model_version: str | None = None

    @field_validator("model_version", mode="before")
    @classmethod
    def _empty_means_unknown(cls, value: str | None) -> str | None:
        """Chuỗi rỗng và None là cùng một ý: chưa biết model nào.

        Tầng DB buộc phải lưu "" chứ không NULL, vì SQL coi mọi NULL là khác
        nhau nên khoá duy nhất (trace_id, model_version) sẽ không chặn được gì.
        Không chuẩn hoá ở đây thì code phía sau kiểm `is None` sẽ trượt với
        đúng những dòng đọc lên từ DB.
        """
        return value or None
    mode: InvokeMode
    status: RunStatus
    input_uri: str | None = None
    output: dict[str, Any] | None = None
    latency_ms: int | None = None
    error: str | None = None
    created_at: datetime


class RunsResponse(BaseModel):
    runs: list[RunRecord] = Field(default_factory=list)
    total: int = 0
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Chạy: `uv run pytest packages/vypq-contracts -v`
Mong đợi: 16 test mới PASS, toàn bộ test cũ vẫn PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . --fix
git add packages/vypq-contracts
git commit -m "feat(contracts): schema cho gateway, host registry và lịch sử chạy"
```

---

### Task 2: Service tự mô tả qua `/v1/info`

Gateway cần biết service làm được gì mà không phải đọc file trên máy khác. Plan A
để capability trong `service.yaml`, chỉ đọc được tại chỗ.

**Files:**
- Create: `packages/vypq-core/src/vypq_core/service_info.py`
- Modify: `services/ocr/src/ocr_service/main.py`, `services/asr/src/asr_service/main.py`
- Modify: `services/_template/src/__PKG__/main.py`
- Delete: `services/ocr/service.yaml`, `services/asr/service.yaml`, `services/_template/service.yaml`
- Test: `packages/vypq-core/tests/test_service_info.py`, bổ sung `services/ocr/tests/test_api.py`

**Interfaces:**
- Consumes: `vypq_contracts.gateway.ServiceInfo`, `vypq_core.app.create_app`
- Produces: `build_info_router(info: ServiceInfo) -> APIRouter` — gắn `GET /v1/info`

- [ ] **Step 1: Viết test trước**

`packages/vypq-core/tests/test_service_info.py`:
```python
import httpx

from vypq_contracts.common import Task
from vypq_contracts.gateway import ServiceInfo
from vypq_core.app import create_app
from vypq_core.config import BaseServiceSettings
from vypq_core.service_info import build_info_router

INFO = ServiceInfo(
    name="ocr", task=Task.OCR, capability_input="image",
    capability_output="text_boxes", version="0.1.0", invoke_path="/v1/ocr",
    default_model="m1",
)


def _client() -> httpx.AsyncClient:
    app = create_app(
        BaseServiceSettings(service_name="ocr", version="0.1.0"),
        routers=[build_info_router(INFO)],
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_info_endpoint_returns_the_manifest():
    async with _client() as c:
        resp = await c.get("/v1/info")
    assert resp.status_code == 200
    assert resp.json() == INFO.model_dump(mode="json")


async def test_info_is_not_authenticated():
    # Service nằm trong mạng nội bộ sau gateway; /v1/info không có bí mật gì.
    async with _client() as c:
        assert (await c.get("/v1/info")).status_code == 200
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest packages/vypq-core/tests/test_service_info.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'vypq_core.service_info'`

- [ ] **Step 3: Viết service_info.py**

`packages/vypq-core/src/vypq_core/service_info.py`:
```python
from fastapi import APIRouter

from vypq_contracts.gateway import ServiceInfo


def build_info_router(info: ServiceInfo) -> APIRouter:
    """Router `/v1/info` để gateway hỏi service tự mô tả mình.

    Plan A để capability trong `service.yaml` — chỉ đọc được khi đứng cùng máy.
    Gateway ở máy khác nên cần một đường HTTP.
    """
    router = APIRouter(prefix="/v1")

    @router.get("/info", response_model=ServiceInfo)
    async def get_info() -> ServiceInfo:
        return info

    return router
```

- [ ] **Step 4: Gắn vào service ocr**

Trong `services/ocr/src/ocr_service/main.py`, trong `build_app_with`, dựng `ServiceInfo`
và thêm router. Sửa chữ ký thành:
```python
def build_app_with(handler: OcrHandler, settings: OcrSettings, backend=None, lifespan=None):
    router = APIRouter(prefix="/v1")
    info = ServiceInfo(
        name=settings.service_name,
        task=Task.OCR,
        capability_input="image",
        capability_output="text_boxes",
        version=settings.version,
        invoke_path="/v1/ocr",
        default_model=settings.default_model,
    )
    ...
    return create_app(
        settings,
        routers=[router, build_info_router(info)],
        readiness={"model_host": _upstream_ready},
        lifespan=lifespan,
    )
```
với import `from vypq_contracts.gateway import ServiceInfo` và
`from vypq_core.service_info import build_info_router`.

- [ ] **Step 5: Thêm test cho service ocr**

Vào `services/ocr/tests/test_api.py`, ngay trước `test_trace_id_header_is_echoed_back`:
```python
async def test_service_advertises_its_capability():
    # Gateway dựa vào đây để biết service nhận gì, trả gì, và model mặc định.
    async with _client(_app(FakeOcrBackend(RawOcrOutput()))) as c:
        resp = await c.get("/v1/info")
    body = resp.json()
    assert body["name"] == "ocr"
    assert body["task"] == "ocr"
    assert body["capability_input"] == "image"
    assert body["invoke_path"] == "/v1/ocr"
    assert body["default_model"] == "m1"
```

- [ ] **Step 6: Làm tương tự cho asr và template**

`services/asr/src/asr_service/main.py` — giống hệt nhưng `Task.ASR`,
`capability_input="audio"`, `capability_output="transcript"`, `invoke_path="/v1/asr"`.

`services/_template/src/__PKG__/main.py` — dùng token: `Task.__TASKUPPER__`,
`capability_input="bytes"`, `capability_output="json"`, `invoke_path="/v1/__SLUG__"`.
**Đọc route thật trong file** rồi đặt `invoke_path` cho khớp — đây là hợp đồng
gateway dựa vào, sai một ký tự là 404 lúc chạy. Thêm assert vào test sinh service:
`assert "/v1/" in generated_info["invoke_path"]`.

- [ ] **Step 7: Chạy test và kiểm generator**

```bash
uv run pytest packages/vypq-core services/ocr services/asr -v
./scripts/new-service.sh probeinfo asr 8091 && uv run pytest services/probeinfo -q
rm -rf services/probeinfo && git checkout -- pyproject.toml uv.lock && uv sync
```
Mong đợi: tất cả PASS; service sinh ra cũng có `/v1/info`.

- [ ] **Step 8: Commit**

```bash
uv run ruff check . --fix
git add packages services
git commit -m "feat(core): endpoint /v1/info để service tự mô tả cho gateway"
```

---
### Task 3: Khung gateway, DB và repository

**Files:**
- Create: `apps/gateway/pyproject.toml`, `apps/gateway/alembic.ini`
- Create: `apps/gateway/migrations/{env.py,script.py.mako}`, `apps/gateway/migrations/versions/.gitkeep`
- Create: `apps/gateway/src/gateway/{__init__,settings}.py`
- Create: `apps/gateway/src/gateway/db/{__init__,engine,models,repo}.py`
- Test: `apps/gateway/tests/test_host_repo.py`

**Interfaces:**
- Consumes: `vypq_core.config.BaseServiceSettings`, `vypq_contracts.gateway.{HostState, HostRegistration}`
- Produces:
  - `GatewaySettings(service_name, port, database_url, brokers, services_path, poll_interval_s, host_ttl_s)`
  - `Base` (DeclarativeBase), models `Host`, `Run`
  - `make_engine(url) -> AsyncEngine`, `make_session_factory(engine) -> async_sessionmaker`
  - `HostRepo(session)` — `await upsert(reg) -> HostState`, `await get(name) -> HostState | None`, `await list_all() -> list[HostState]`, `await delete(name) -> bool`, `await mark_polled(name, healthy, models, error) -> None`, `await token_for(name) -> str | None`

**Vì sao dùng JSON chứ không JSONB/ARRAY:** lệnh test mặc định phải chạy được không
cần Docker, nên repository test chạy trên SQLite in-memory. Kiểu cột riêng của
Postgres sẽ khiến cùng một model không dựng nổi bảng trên SQLite.

- [ ] **Step 1: Tạo pyproject và đăng ký workspace**

`apps/gateway/pyproject.toml`:
```toml
[project]
name = "gateway"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "vypq-contracts",
    "vypq-core",
    "vypq-events",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy[asyncio]>=2.0.36",
    "alembic>=1.14",
    "asyncpg>=0.30",
    "httpx>=0.27",
    "pyyaml>=6.0",
    "prometheus-client>=0.21",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/gateway"]

[tool.uv.sources]
vypq-contracts = { workspace = true }
vypq-core = { workspace = true }
vypq-events = { workspace = true }
```

Đăng ký vào root `pyproject.toml`: thêm `"gateway",` trước `# <<< workspace members`
và `gateway = { workspace = true }` trước `# <<< workspace sources`. Thêm
`"aiosqlite>=0.20"` vào `[dependency-groups] dev` (test repository dùng SQLite).
Rồi `uv sync`.

- [ ] **Step 2: Viết test trước**

`apps/gateway/tests/test_host_repo.py`:
```python
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import Base
from gateway.db.repo import HostRepo
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.gateway import HostRegistration
from vypq_contracts.hosting import ModelInfo


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _model(mid: str = "m1") -> ModelInfo:
    return ModelInfo(id=mid, task=Task.OCR, kind=ModelKind.OPENSOURCE, runner="paddle")


async def test_upsert_creates_then_returns_the_host(session):
    repo = HostRepo(session)
    state = await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000", token="t"))
    assert state.name == "gpu-1"
    assert state.healthy is False          # chưa poll thì chưa biết
    assert (await repo.get("gpu-1")).url == "http://h:9000"


async def test_upsert_twice_updates_url_instead_of_duplicating(session):
    # Máy thuê lại giữ nguyên tên nhưng đổi URL ngrok — phải cập nhật, không nhân bản.
    repo = HostRepo(session)
    await repo.upsert(HostRegistration(name="gpu-1", url="http://cu:9000"))
    await repo.upsert(HostRegistration(name="gpu-1", url="http://moi:9000"))
    hosts = await repo.list_all()
    assert len(hosts) == 1
    assert hosts[0].url == "http://moi:9000"


async def test_reregistering_resets_health_until_polled_again(session):
    # URL mới nghĩa là máy khác. Giữ lại healthy=True của máy cũ sẽ khiến gateway
    # định tuyến vào một tunnel chưa ai kiểm chứng.
    repo = HostRepo(session)
    await repo.upsert(HostRegistration(name="gpu-1", url="http://cu:9000"))
    await repo.mark_polled("gpu-1", healthy=True, models=[_model()], error=None)
    assert (await repo.get("gpu-1")).healthy is True

    await repo.upsert(HostRegistration(name="gpu-1", url="http://moi:9000"))
    state = await repo.get("gpu-1")
    assert state.healthy is False
    assert state.models == []


async def test_mark_polled_records_models_and_timestamp(session):
    repo = HostRepo(session)
    await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000"))
    before = datetime.now(UTC)
    await repo.mark_polled("gpu-1", healthy=True, models=[_model("a"), _model("b")], error=None)
    state = await repo.get("gpu-1")
    assert [m.id for m in state.models] == ["a", "b"]
    assert state.last_seen_at >= before
    assert state.last_error is None


async def test_mark_polled_failure_keeps_the_reason(session):
    repo = HostRepo(session)
    await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000"))
    await repo.mark_polled("gpu-1", healthy=False, models=[], error="connect timeout")
    state = await repo.get("gpu-1")
    assert state.healthy is False
    assert state.last_error == "connect timeout"


async def test_token_is_readable_by_the_repo_but_absent_from_state(session):
    repo = HostRepo(session)
    await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000", token="bi-mat"))
    assert await repo.token_for("gpu-1") == "bi-mat"
    assert "bi-mat" not in (await repo.get("gpu-1")).model_dump_json()


async def test_delete_removes_the_host(session):
    repo = HostRepo(session)
    await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000"))
    assert await repo.delete("gpu-1") is True
    assert await repo.get("gpu-1") is None
    assert await repo.delete("gpu-1") is False


async def test_get_unknown_host_returns_none(session):
    assert await HostRepo(session).get("khong-co") is None
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/gateway -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'gateway'`

- [ ] **Step 4: Viết settings.py**

`apps/gateway/src/gateway/settings.py`:
```python
from pathlib import Path

from vypq_core.config import BaseServiceSettings


class GatewaySettings(BaseServiceSettings):
    service_name: str = "gateway"
    port: int = 8080
    database_url: str = "postgresql+asyncpg://vypq:vypq@localhost:5432/vypq"
    brokers: str = "localhost:9092"
    services_path: Path = Path("config/services.yaml")
    poll_interval_s: float = 15.0
    # Quá hạn này mà không poll thành công thì host bị coi là chết và gỡ khỏi
    # định tuyến. Gấp 3 chu kỳ poll: một lần trượt vì mạng chập không nên hạ máy.
    host_ttl_s: float = 45.0
```

- [ ] **Step 5: Viết db/engine.py và db/models.py**

`apps/gateway/src/gateway/db/engine.py`:
```python
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
```

`apps/gateway/src/gateway/db/models.py`:
```python
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
```

- [ ] **Step 6: Viết db/repo.py**

`apps/gateway/src/gateway/db/repo.py`:
```python
from datetime import UTC, datetime

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import Host
from vypq_contracts.gateway import HostRegistration, HostState
from vypq_contracts.hosting import ModelInfo


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
        await self._s.commit()
        return _to_state(row)

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
```

`apps/gateway/src/gateway/__init__.py` và `apps/gateway/src/gateway/db/__init__.py`:
```python
__all__: list[str] = []
```

- [ ] **Step 7: Chạy test để xác nhận pass**

Chạy: `uv run pytest apps/gateway -v`
Mong đợi: 8 PASS

- [ ] **Step 8: Dựng alembic và migration đầu tiên**

```bash
cd apps/gateway
uv run alembic init -t async migrations
```
Sửa `alembic.ini`: `sqlalchemy.url =` để trống (lấy từ env lúc chạy).
Sửa `migrations/env.py`: `from gateway.db.models import Base` và
`target_metadata = Base.metadata`; đọc URL từ `os.environ["VYPQ_DATABASE_URL"]`.

Thêm Postgres vào `infra/compose/docker-compose.dev.yml`:
```yaml
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: vypq
      POSTGRES_PASSWORD: vypq
      POSTGRES_DB: vypq
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U vypq"]
      interval: 5s
      retries: 20
```

```bash
docker compose -f ../../infra/compose/docker-compose.dev.yml up -d postgres
sleep 8
VYPQ_DATABASE_URL=postgresql+asyncpg://vypq:vypq@localhost:5432/vypq \
  uv run alembic revision --autogenerate -m "hosts va runs"
VYPQ_DATABASE_URL=postgresql+asyncpg://vypq:vypq@localhost:5432/vypq \
  uv run alembic upgrade head
```
Mong đợi: sinh ra file trong `migrations/versions/`, `upgrade head` chạy sạch.

- [ ] **Step 9: Test tích hợp trên Postgres thật**

`apps/gateway/tests/test_repo_postgres.py`:
```python
import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import Base
from gateway.db.repo import HostRepo
from vypq_contracts.gateway import HostRegistration

pytestmark = pytest.mark.slow

URL = os.environ.get(
    "VYPQ_TEST_DATABASE_URL", "postgresql+asyncpg://vypq:vypq@localhost:5432/vypq"
)


async def test_schema_works_on_real_postgres():
    # SQLite chấp nhận nhiều thứ Postgres từ chối. Chạy đúng schema này trên
    # Postgres thật ít nhất một lần, nếu không migration sẽ vỡ lúc deploy.
    engine = create_async_engine(URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        repo = HostRepo(s)
        await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000", token="t"))
        assert (await repo.get("gpu-1")).name == "gpu-1"
        assert await repo.delete("gpu-1") is True
    await engine.dispose()
```

Chạy: `uv run pytest apps/gateway -m slow -v`
Mong đợi: 1 PASS

- [ ] **Step 10: Commit**

```bash
uv run ruff check . --fix
git add apps/gateway infra pyproject.toml uv.lock
git commit -m "feat(gateway): khung app, schema DB và repository cho host"
```

---
### Task 4: API đăng ký host

**Files:**
- Create: `apps/gateway/src/gateway/api/{__init__,hosts}.py`
- Create: `apps/gateway/src/gateway/main.py`
- Test: `apps/gateway/tests/test_hosts_api.py`

**Interfaces:**
- Consumes: `HostRepo` từ Task 3, `vypq_core.app.create_app`
- Produces:
  - `build_hosts_router(session_factory, settings) -> APIRouter` với `POST /v1/hosts`, `GET /v1/hosts`, `DELETE /v1/hosts/{name}`
  - `build_app(session_factory, settings, routers=()) -> FastAPI`

- [ ] **Step 1: Viết test trước**

`apps/gateway/tests/test_hosts_api.py`:
```python
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.api.hosts import build_hosts_router
from gateway.db.models import Base
from gateway.main import build_app
from gateway.settings import GatewaySettings


@pytest.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = GatewaySettings(service_name="gateway")
    app = build_app(factory, settings, routers=[build_hosts_router(factory, settings)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c
    await engine.dispose()


async def test_register_then_list(client):
    resp = await client.post(
        "/v1/hosts", json={"name": "gpu-1", "url": "https://a.ngrok.app", "token": "t"}
    )
    assert resp.status_code == 201
    listed = (await client.get("/v1/hosts")).json()["hosts"]
    assert [h["name"] for h in listed] == ["gpu-1"]
    assert listed[0]["healthy"] is False       # chưa poll thì chưa khoẻ


async def test_listing_never_leaks_the_token(client):
    await client.post(
        "/v1/hosts", json={"name": "gpu-1", "url": "http://h:9000", "token": "bi-mat"}
    )
    body = (await client.get("/v1/hosts")).text
    assert "bi-mat" not in body


async def test_reregister_updates_url(client):
    await client.post("/v1/hosts", json={"name": "gpu-1", "url": "http://cu:9000"})
    await client.post("/v1/hosts", json={"name": "gpu-1", "url": "http://moi:9000"})
    listed = (await client.get("/v1/hosts")).json()["hosts"]
    assert len(listed) == 1
    assert listed[0]["url"] == "http://moi:9000"


async def test_delete_host(client):
    await client.post("/v1/hosts", json={"name": "gpu-1", "url": "http://h:9000"})
    assert (await client.delete("/v1/hosts/gpu-1")).status_code == 204
    assert (await client.get("/v1/hosts")).json()["hosts"] == []


async def test_delete_unknown_host_is_404(client):
    assert (await client.delete("/v1/hosts/khong-co")).status_code == 404


async def test_register_rejects_missing_url(client):
    assert (await client.post("/v1/hosts", json={"name": "gpu-1"})).status_code == 422


async def test_health_is_available(client):
    assert (await client.get("/health")).status_code == 200
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/gateway/tests/test_hosts_api.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'gateway.api'`

- [ ] **Step 3: Viết api/hosts.py**

`apps/gateway/src/gateway/api/hosts.py`:
```python
from fastapi import APIRouter, Response

from gateway.db.repo import HostRepo
from gateway.settings import GatewaySettings
from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import HostRegistration, HostsResponse, HostState
from vypq_core.errors import ServiceError


def build_hosts_router(session_factory, settings: GatewaySettings) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.post("/hosts", response_model=HostState, status_code=201)
    async def register(reg: HostRegistration) -> HostState:
        async with session_factory() as session:
            return await HostRepo(session).upsert(reg)

    @router.get("/hosts", response_model=HostsResponse)
    async def list_hosts() -> HostsResponse:
        async with session_factory() as session:
            return HostsResponse(hosts=await HostRepo(session).list_all())

    @router.delete("/hosts/{name}", status_code=204)
    async def delete_host(name: str) -> Response:
        async with session_factory() as session:
            if not await HostRepo(session).delete(name):
                raise ServiceError(
                    ErrorCode.BAD_INPUT, f"không có host tên '{name}'", http_status=404
                )
        return Response(status_code=204)

    return router
```

- [ ] **Step 4: Viết main.py**

`apps/gateway/src/gateway/main.py`:
```python
from collections.abc import Sequence

from fastapi import APIRouter, FastAPI

from gateway.settings import GatewaySettings
from vypq_core.app import create_app


def build_app(
    session_factory,
    settings: GatewaySettings,
    routers: Sequence[APIRouter] = (),
    lifespan=None,
) -> FastAPI:
    return create_app(settings, routers=list(routers), lifespan=lifespan)
```

`apps/gateway/src/gateway/api/__init__.py`:
```python
__all__: list[str] = []
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Chạy: `uv run pytest apps/gateway -v`
Mong đợi: 15 PASS, 1 deselected

- [ ] **Step 6: Commit**

```bash
uv run ruff check . --fix
git add apps/gateway
git commit -m "feat(gateway): API đăng ký, liệt kê và gỡ host"
```

---

### Task 5: Poller — gateway hỏi ra từng máy GPU

**Files:**
- Create: `apps/gateway/src/gateway/registry/{__init__,poller}.py`
- Test: `apps/gateway/tests/test_poller.py`

**Interfaces:**
- Consumes: `HostRepo`, `vypq_core.http_client.UpstreamClient`
- Produces: `HostPoller(session_factory, settings, client_factory=None)` — `await poll_once() -> int` (số host đã poll), `await run()`

**Chiều gọi:** gateway poll RA host, không phải host tự đăng ký ngược về. Máy ứng
dụng cũng nằm sau NAT, còn ngrok chỉ mở một chiều vào máy GPU — poll ra là chiều
duy nhất chạy được mà không phải phơi thêm gì ra Internet.

- [ ] **Step 1: Viết test trước**

`apps/gateway/tests/test_poller.py`:
```python
import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import Base
from gateway.db.repo import HostRepo
from gateway.registry.poller import HostPoller
from gateway.settings import GatewaySettings
from vypq_contracts.gateway import HostRegistration

MODELS_BODY = {
    "host_name": "gpu-1",
    "models": [
        {"id": "m1", "task": "ocr", "kind": "opensource", "runner": "paddle",
         "loaded": False, "available": True, "vram_mb": 2500},
    ],
}


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _register(factory, name="gpu-1", url="http://h:9000", token="t"):
    async with factory() as s:
        await HostRepo(s).upsert(HostRegistration(name=name, url=url, token=token))


def _poller(factory) -> HostPoller:
    return HostPoller(factory, GatewaySettings(service_name="gateway"))


@respx.mock
async def test_poll_marks_host_healthy_and_stores_models(factory):
    await _register(factory)
    respx.get("http://h:9000/v1/models").mock(return_value=httpx.Response(200, json=MODELS_BODY))
    assert await _poller(factory).poll_once() == 1
    async with factory() as s:
        state = await HostRepo(s).get("gpu-1")
    assert state.healthy is True
    assert [m.id for m in state.models] == ["m1"]


@respx.mock
async def test_poll_sends_the_host_token(factory):
    await _register(factory, token="bi-mat")
    captured = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=MODELS_BODY)

    respx.get("http://h:9000/v1/models").mock(side_effect=_record)
    await _poller(factory).poll_once()
    assert captured["auth"] == "Bearer bi-mat"


@respx.mock
async def test_unreachable_host_becomes_unhealthy_with_a_reason(factory):
    await _register(factory)
    respx.get("http://h:9000/v1/models").mock(side_effect=httpx.ConnectError("mất kết nối"))
    await _poller(factory).poll_once()
    async with factory() as s:
        state = await HostRepo(s).get("gpu-1")
    assert state.healthy is False
    assert "mất kết nối" in state.last_error


@respx.mock
async def test_wrong_token_marks_unhealthy_not_healthy(factory):
    # Máy thuê lại đổi token: host vẫn trả lời nhưng ta không dùng được nó.
    await _register(factory)
    respx.get("http://h:9000/v1/models").mock(return_value=httpx.Response(401))
    await _poller(factory).poll_once()
    async with factory() as s:
        assert (await HostRepo(s).get("gpu-1")).healthy is False


@respx.mock
async def test_one_dead_host_does_not_stop_the_others(factory):
    await _register(factory, name="gpu-1", url="http://a:9000")
    await _register(factory, name="gpu-2", url="http://b:9000")
    respx.get("http://a:9000/v1/models").mock(side_effect=httpx.ConnectError("chết"))
    respx.get("http://b:9000/v1/models").mock(
        return_value=httpx.Response(200, json=MODELS_BODY)
    )
    assert await _poller(factory).poll_once() == 2
    async with factory() as s:
        repo = HostRepo(s)
        assert (await repo.get("gpu-1")).healthy is False
        assert (await repo.get("gpu-2")).healthy is True


@respx.mock
async def test_malformed_models_body_marks_unhealthy(factory):
    # model-host phiên bản khác trả shape lạ: coi như không dùng được, không nổ.
    await _register(factory)
    respx.get("http://h:9000/v1/models").mock(
        return_value=httpx.Response(200, json={"khong": "dung shape"})
    )
    await _poller(factory).poll_once()
    async with factory() as s:
        state = await HostRepo(s).get("gpu-1")
    assert state.healthy is False
    assert state.last_error


async def test_poll_with_no_hosts_is_a_noop(factory):
    assert await _poller(factory).poll_once() == 0
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/gateway/tests/test_poller.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'gateway.registry'`

- [ ] **Step 3: Viết registry/poller.py**

`apps/gateway/src/gateway/registry/poller.py`:
```python
import asyncio

import httpx

from gateway.db.repo import HostRepo
from gateway.settings import GatewaySettings
from vypq_contracts.hosting import ModelsResponse
from vypq_core.logging import get_logger

log = get_logger(__name__)


class HostPoller:
    """Hỏi ra từng máy GPU xem nó còn sống và đang phục vụ model nào.

    Chiều gọi là RA, không phải host tự đăng ký về: máy ứng dụng cũng sau NAT,
    còn ngrok chỉ mở một chiều vào máy GPU.
    """

    def __init__(self, session_factory, settings: GatewaySettings) -> None:
        self._factory = session_factory
        self._settings = settings

    async def poll_once(self) -> int:
        async with self._factory() as session:
            hosts = await HostRepo(session).list_all()
        if not hosts:
            return 0
        # Poll song song: một máy treo 30s không được chặn những máy khác.
        await asyncio.gather(*(self._poll_host(h.name, h.url) for h in hosts))
        return len(hosts)

    async def _poll_host(self, name: str, url: str) -> None:
        async with self._factory() as session:
            repo = HostRepo(session)
            token = await repo.token_for(name)
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            try:
                async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                    response = await client.get(f"{url.rstrip('/')}/v1/models")
                if response.status_code >= 400:
                    raise RuntimeError(f"trả {response.status_code}")
                models = ModelsResponse.model_validate(response.json()).models
            except Exception as exc:
                # Mọi lỗi đều chỉ hạ đúng một host. Một máy thuê chết không được
                # kéo theo vòng poll của những máy còn lại.
                log.warning("host_poll_failed", host=name, error=str(exc))
                await repo.mark_polled(name, healthy=False, models=[], error=str(exc))
                return
            await repo.mark_polled(name, healthy=True, models=models, error=None)

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # noqa: BLE001 - vòng nền không được chết
                log.exception("poll_loop_error", error=str(exc))
            await asyncio.sleep(self._settings.poll_interval_s)
```

`apps/gateway/src/gateway/registry/__init__.py`:
```python
__all__: list[str] = []
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Chạy: `uv run pytest apps/gateway -v`
Mong đợi: 22 PASS, 1 deselected

- [ ] **Step 5: Commit**

```bash
uv run ruff check . --fix
git add apps/gateway
git commit -m "feat(gateway): poller hỏi ra máy GPU, ghi trạng thái và danh mục model"
```

---
### Task 6: Endpoint discovery cho service, có TTL

`GET /v1/hosts` ở Task 4 dành cho người và dashboard nên **không** mang token.
Service thì cần token để gọi model-host, nên có một đường riêng.

**Files:**
- Create: `apps/gateway/src/gateway/api/discovery.py`
- Modify: `packages/vypq-core/src/vypq_core/host_registry.py` (thêm `DiscoveryResponse`)
- Test: `apps/gateway/tests/test_discovery_api.py`

**Interfaces:**
- Consumes: `HostRepo`, `vypq_core.host_registry.HostRef`
- Produces:
  - `DiscoveryResponse(hosts: list[HostRef])` trong `vypq_core.host_registry`
  - `build_discovery_router(session_factory, settings) -> APIRouter` với `GET /v1/discovery/hosts`

**Vì sao TTL được áp lúc ĐỌC, không phải lúc poll:** nếu vòng poll bị treo hoặc
chết, cờ `healthy` trong DB đóng băng ở giá trị cuối và gateway tiếp tục phát
một máy đã chết cho mọi service. Kiểm hạn ngay lúc trả lời khiến poller hỏng
biểu hiện thành "không có host nào", chứ không phải "mọi host đều khoẻ".

- [ ] **Step 1: Viết test trước**

`apps/gateway/tests/test_discovery_api.py`:
```python
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.api.discovery import build_discovery_router
from gateway.db.models import Base, Host
from gateway.db.repo import HostRepo
from gateway.main import build_app
from gateway.settings import GatewaySettings
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.gateway import HostRegistration
from vypq_contracts.hosting import ModelInfo

SETTINGS = GatewaySettings(service_name="gateway", host_ttl_s=45.0)


@pytest.fixture
async def ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = build_app(factory, SETTINGS, routers=[build_discovery_router(factory, SETTINGS)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c, factory
    await engine.dispose()


def _model() -> ModelInfo:
    return ModelInfo(id="m1", task=Task.OCR, kind=ModelKind.OPENSOURCE, runner="paddle")


async def _healthy_host(factory, name="gpu-1", seen_ago_s=0.0):
    async with factory() as s:
        await HostRepo(s).upsert(
            HostRegistration(name=name, url="http://h:9000", token="bi-mat")
        )
        await HostRepo(s).mark_polled(name, healthy=True, models=[_model()], error=None)
        row = await s.get(Host, name)
        row.last_seen_at = datetime.now(UTC) - timedelta(seconds=seen_ago_s)
        await s.commit()


async def test_discovery_includes_the_token(ctx):
    client, factory = ctx
    await _healthy_host(factory)
    hosts = (await client.get("/v1/discovery/hosts")).json()["hosts"]
    assert hosts[0]["token"] == "bi-mat"
    assert hosts[0]["healthy"] is True
    assert [m["id"] for m in hosts[0]["models"]] == ["m1"]


async def test_stale_host_is_served_as_unhealthy(ctx):
    # Poller treo -> cờ healthy đóng băng. Kiểm hạn lúc đọc để hỏng biểu hiện
    # thành "không có host", chứ không phải "mọi host đều khoẻ".
    client, factory = ctx
    await _healthy_host(factory, seen_ago_s=120.0)
    hosts = (await client.get("/v1/discovery/hosts")).json()["hosts"]
    assert hosts[0]["healthy"] is False


async def test_host_seen_recently_stays_healthy(ctx):
    client, factory = ctx
    await _healthy_host(factory, seen_ago_s=10.0)
    assert (await client.get("/v1/discovery/hosts")).json()["hosts"][0]["healthy"] is True


async def test_never_polled_host_is_unhealthy(ctx):
    client, factory = ctx
    async with factory() as s:
        await HostRepo(s).upsert(HostRegistration(name="gpu-1", url="http://h:9000"))
    assert (await client.get("/v1/discovery/hosts")).json()["hosts"][0]["healthy"] is False


async def test_empty_registry_returns_empty_list(ctx):
    client, _ = ctx
    assert (await client.get("/v1/discovery/hosts")).json()["hosts"] == []
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/gateway/tests/test_discovery_api.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'gateway.api.discovery'`

- [ ] **Step 3: Thêm DiscoveryResponse vào vypq-core**

Cuối `packages/vypq-core/src/vypq_core/host_registry.py`:
```python
class DiscoveryResponse(BaseModel):
    """Thân trả lời của gateway cho service hỏi danh sách host.

    Dùng `HostRef` nguyên vẹn — CÓ token — vì service cần token để gọi
    model-host. Endpoint này chỉ được phơi trong mạng nội bộ, khác với
    `GET /v1/hosts` dành cho dashboard và không mang token.
    """

    hosts: list[HostRef] = Field(default_factory=list)
```

- [ ] **Step 4: Viết api/discovery.py**

`apps/gateway/src/gateway/api/discovery.py`:
```python
from datetime import UTC, datetime

from fastapi import APIRouter

from gateway.db.repo import HostRepo
from gateway.settings import GatewaySettings
from vypq_core.host_registry import DiscoveryResponse, HostRef


def build_discovery_router(session_factory, settings: GatewaySettings) -> APIRouter:
    router = APIRouter(prefix="/v1/discovery")

    @router.get("/hosts", response_model=DiscoveryResponse)
    async def hosts() -> DiscoveryResponse:
        now = datetime.now(UTC)
        async with session_factory() as session:
            repo = HostRepo(session)
            states = await repo.list_all()
            refs: list[HostRef] = []
            for state in states:
                # Kiểm hạn LÚC ĐỌC: poller treo thì cờ healthy trong DB đóng
                # băng ở giá trị cuối, và gateway sẽ phát một máy đã chết cho
                # mọi service. Tính lại ở đây khiến poller hỏng biểu hiện thành
                # "không có host nào", chứ không phải "mọi host đều khoẻ".
                fresh = (
                    state.last_seen_at is not None
                    and (now - state.last_seen_at).total_seconds() <= settings.host_ttl_s
                )
                refs.append(
                    HostRef(
                        name=state.name,
                        url=state.url,
                        token=await repo.token_for(state.name),
                        models=state.models,
                        healthy=state.healthy and fresh,
                    )
                )
        return DiscoveryResponse(hosts=refs)

    return router
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Chạy: `uv run pytest apps/gateway packages/vypq-core -v`
Mong đợi: tất cả PASS

- [ ] **Step 6: Commit**

```bash
uv run ruff check . --fix
git add apps/gateway packages/vypq-core
git commit -m "feat(gateway): endpoint discovery cho service, kiểm hạn lúc đọc"
```

---

### Task 7: `DiscoveryHostRegistry` trong vypq-core

**Files:**
- Modify: `packages/vypq-core/src/vypq_core/host_registry.py`
- Modify: `pyproject.toml` (thêm `mypy` vào dev), `Makefile`
- Test: `packages/vypq-core/tests/test_discovery_registry.py`

**Interfaces:**
- Consumes: `HostRegistry` Protocol, `HostRef`, `DiscoveryResponse`
- Produces: `DiscoveryHostRegistry(url: str, *, refresh_s: float = 15.0, fallback: list[HostRef] | None = None, client=None, clock=time.monotonic)` — cài đủ `hosts()`, `pick()`, `models_for_task()`, `lease()`

**Điểm mấu chốt:** cùng Protocol với `StaticHostRegistry` nên không service nào
phải sửa logic. `pick()`, `models_for_task()`, `lease()` **tái dùng** phần thân
của bản static thay vì chép lại — hai bản chép tay sẽ trôi khỏi nhau.

- [ ] **Step 1: Viết test trước**

`packages/vypq-core/tests/test_discovery_registry.py`:
```python
import httpx
import pytest
import respx

from vypq_contracts.common import ModelKind, Task
from vypq_contracts.hosting import ModelInfo
from vypq_core.host_registry import (
    DiscoveryHostRegistry,
    HostRef,
    HostRegistry,
    NoHostAvailableError,
)

URL = "http://gateway:8080/v1/discovery/hosts"


def _body(*hosts: dict) -> dict:
    return {"hosts": list(hosts)}


def _host(name: str, healthy: bool = True, model: str = "m1") -> dict:
    return {
        "name": name, "url": f"http://{name}:9000", "token": "t", "healthy": healthy,
        "inflight": 0,
        "models": [
            {"id": model, "task": "ocr", "kind": "opensource", "runner": "paddle",
             "loaded": False, "available": True, "vram_mb": 0}
        ],
    }


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


@respx.mock
async def test_fetches_hosts_from_the_gateway():
    respx.get(URL).mock(return_value=httpx.Response(200, json=_body(_host("a"))))
    reg = DiscoveryHostRegistry(URL)
    assert [h.name for h in await reg.hosts()] == ["a"]
    await reg.aclose()


@respx.mock
async def test_result_is_cached_until_refresh_window_elapses():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=_body(_host("a"))))
    clock = Clock()
    reg = DiscoveryHostRegistry(URL, refresh_s=15.0, clock=clock)
    await reg.hosts()
    await reg.hosts()
    assert route.call_count == 1          # trong cửa sổ thì không hỏi lại
    clock.now = 20.0
    await reg.hosts()
    assert route.call_count == 2
    await reg.aclose()


@respx.mock
async def test_new_host_appears_without_restarting_the_service():
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json=_body(_host("a"))),
            httpx.Response(200, json=_body(_host("a"), _host("b"))),
        ]
    )
    clock = Clock()
    reg = DiscoveryHostRegistry(URL, refresh_s=15.0, clock=clock)
    assert len(await reg.hosts()) == 1
    clock.now = 20.0
    assert len(await reg.hosts()) == 2
    assert route.call_count == 2
    await reg.aclose()


@respx.mock
async def test_gateway_down_keeps_serving_the_last_known_list():
    # Gateway sập KHÔNG được kéo theo mọi service. Danh sách cũ vẫn tốt hơn
    # danh sách rỗng: host trong đó có thể vẫn đang chạy bình thường.
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json=_body(_host("a"))),
            httpx.ConnectError("gateway chết"),
        ]
    )
    clock = Clock()
    reg = DiscoveryHostRegistry(URL, refresh_s=15.0, clock=clock)
    await reg.hosts()
    clock.now = 20.0
    assert [h.name for h in await reg.hosts()] == ["a"]
    await reg.aclose()


@respx.mock
async def test_first_fetch_failing_falls_back_to_static_list():
    respx.get(URL).mock(side_effect=httpx.ConnectError("gateway chưa lên"))
    fallback = [HostRef(name="du-phong", url="http://d:9000",
                        models=[ModelInfo(id="m1", task=Task.OCR,
                                          kind=ModelKind.OPENSOURCE, runner="p")])]
    reg = DiscoveryHostRegistry(URL, fallback=fallback)
    assert (await reg.pick("m1")).name == "du-phong"
    await reg.aclose()


@respx.mock
async def test_pick_skips_unhealthy_hosts_from_the_gateway():
    respx.get(URL).mock(
        return_value=httpx.Response(200, json=_body(_host("a", healthy=False), _host("b")))
    )
    reg = DiscoveryHostRegistry(URL)
    assert (await reg.pick("m1")).name == "b"
    await reg.aclose()


@respx.mock
async def test_pick_raises_when_nothing_serves_the_model():
    respx.get(URL).mock(return_value=httpx.Response(200, json=_body(_host("a"))))
    reg = DiscoveryHostRegistry(URL)
    with pytest.raises(NoHostAvailableError):
        await reg.pick("khong-co")
    await reg.aclose()


@respx.mock
async def test_lease_tracks_inflight_across_refreshes():
    # inflight sống ở đối tượng HostRef. Refresh dựng HostRef mới thì số đang
    # chạy bị xoá sạch và pick() lại dồn tải. Phải chuyển tiếp qua các lần làm mới.
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=_body(_host("a"))))
    clock = Clock()
    reg = DiscoveryHostRegistry(URL, refresh_s=15.0, clock=clock)
    host = await reg.pick("m1")
    async with reg.lease(host):
        clock.now = 20.0
        refreshed = await reg.hosts()
        assert refreshed[0].inflight == 1
    assert route.call_count == 2
    assert (await reg.hosts())[0].inflight == 0
    await reg.aclose()


async def test_satisfies_the_protocol():
    assert isinstance(DiscoveryHostRegistry(URL), HostRegistry)
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest packages/vypq-core/tests/test_discovery_registry.py -v`
Mong đợi: FAIL với `ImportError: cannot import name 'DiscoveryHostRegistry'`

- [ ] **Step 3: Tách phần dùng chung của StaticHostRegistry**

Trong `packages/vypq-core/src/vypq_core/host_registry.py`, rút ba hàm thuần ra
ngoài để hai bản registry dùng chung, thay vì chép:
```python
def _pick_from(hosts: list[HostRef], model_id: str) -> HostRef:
    candidates = [h for h in hosts if h.healthy and h.has_model(model_id)]
    if not candidates:
        raise NoHostAvailableError(model_id)
    return min(candidates, key=lambda h: h.inflight)


def _models_for_task_from(hosts: list[HostRef], task: Task) -> list[ModelInfo]:
    best: dict[str, tuple[int, ModelInfo]] = {}
    for host in hosts:
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
async def _lease(host: HostRef):
    host.inflight += 1
    try:
        yield host
    finally:
        host.inflight -= 1
```
Rồi `StaticHostRegistry` gọi thẳng ba hàm này:
```python
    async def pick(self, model_id: str) -> HostRef:
        return _pick_from(self._hosts, model_id)

    def models_for_task(self, task: Task) -> list[ModelInfo]:
        return _models_for_task_from(self._hosts, task)

    # BỎ decorator @asynccontextmanager ở đây: nó đã nằm trên `_lease`. Để cả
    # hai chỗ sẽ bọc hai lớp và `async with` nhận về context manager thay vì host.
    def lease(self, host: HostRef):
        return _lease(host)
```
Toàn bộ test cũ của `StaticHostRegistry` phải vẫn xanh, không sửa dòng nào.

- [ ] **Step 4: Viết DiscoveryHostRegistry**

```python
class DiscoveryHostRegistry:
    """Lấy danh sách host từ gateway, làm mới định kỳ.

    Cùng Protocol với StaticHostRegistry nên service không phải sửa gì ngoài
    một dòng config.
    """

    def __init__(
        self,
        url: str,
        *,
        refresh_s: float = 15.0,
        fallback: list[HostRef] | None = None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._refresh_s = refresh_s
        self._clock = clock
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._cached: list[HostRef] = list(fallback or [])
        self._fetched_at: float | None = None

    async def hosts(self) -> list[HostRef]:
        now = self._clock()
        if self._fetched_at is not None and now - self._fetched_at < self._refresh_s:
            return self._cached
        try:
            response = await self._client.get(self._url)
            response.raise_for_status()
            fresh = DiscoveryResponse.model_validate(response.json()).hosts
        except Exception as exc:
            # Gateway sập không được kéo theo mọi service: danh sách cũ vẫn tốt
            # hơn danh sách rỗng, vì host trong đó có thể vẫn đang chạy.
            log.warning("host_discovery_failed", url=self._url, error=str(exc))
            self._fetched_at = now
            return self._cached

        # inflight sống ở đối tượng HostRef. Dựng HostRef mới mỗi lần refresh
        # sẽ xoá sạch số request đang chạy và pick() lại dồn tải vào một host.
        previous = {h.name: h.inflight for h in self._cached}
        for host in fresh:
            host.inflight = previous.get(host.name, 0)
        self._cached = fresh
        self._fetched_at = now
        return self._cached

    async def pick(self, model_id: str) -> HostRef:
        return _pick_from(await self.hosts(), model_id)

    def models_for_task(self, task: Task) -> list[ModelInfo]:
        return _models_for_task_from(self._cached, task)

    def lease(self, host: HostRef):
        return _lease(host)

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 5: Thêm mypy để chặn lệch chữ ký**

`@runtime_checkable` chỉ kiểm method CÓ MẶT. Một bản cài `lease()` thành hàm
sync vẫn lọt `isinstance`. Thêm `"mypy>=1.13"` vào `[dependency-groups] dev`,
thêm target vào `Makefile`:
```makefile
typecheck:
	uv run mypy packages/vypq-core/src/vypq_core/host_registry.py
```
và `packages/vypq-core/tests/test_registry_typing.py`:
```python
import subprocess

import pytest

pytestmark = pytest.mark.slow


def test_both_registries_conform_to_the_protocol_by_type():
    # isinstance chỉ thấy method có mặt, không thấy chữ ký. Đây là chỗ duy nhất
    # bắt được một bản cài lease() thành hàm sync.
    source = """
from vypq_core.host_registry import (
    DiscoveryHostRegistry, HostRegistry, StaticHostRegistry,
)


def use(registry: HostRegistry) -> None: ...


use(StaticHostRegistry([]))
use(DiscoveryHostRegistry("http://x"))
"""
    result = subprocess.run(
        ["uv", "run", "mypy", "--command", source], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

- [ ] **Step 6: Chạy test**

```bash
uv run pytest packages/vypq-core -v
uv run pytest packages/vypq-core/tests/test_registry_typing.py -m slow -v
```
Mong đợi: tất cả PASS. Nếu mypy báo lỗi chữ ký, sửa chữ ký chứ đừng sửa test.

- [ ] **Step 7: Commit**

```bash
uv run ruff check . --fix
git add packages/vypq-core pyproject.toml Makefile uv.lock
git commit -m "feat(core): DiscoveryHostRegistry và kiểm conformance bằng mypy"
```

---
### Task 8: Service chuyển sang lấy host từ gateway

**Files:**
- Modify: `services/ocr/src/ocr_service/settings.py`, `main.py`, `worker.py`
- Modify: `services/asr/...` và `services/_template/...` tương ứng
- Modify: `services/ocr/config.yaml` (đổi `source` sang `gateway`)
- Test: `services/ocr/tests/test_settings.py`

**Interfaces:**
- Consumes: `DiscoveryHostRegistry`, `StaticHostRegistry` từ Task 7
- Produces: `build_host_registry(settings: OcrSettings) -> HostRegistry` trong `settings.py`

Đây là bước mà **một dòng config** đổi cả hành vi — đúng thứ đã thiết kế từ Plan A.

- [ ] **Step 1: Viết test trước**

`services/ocr/tests/test_settings.py`:
```python
from pathlib import Path

from ocr_service.settings import OcrSettings, build_host_registry
from vypq_core.host_registry import DiscoveryHostRegistry, StaticHostRegistry

STATIC = """
host_discovery:
  source: static
  fallback_static:
    - name: gpu-1
      url: http://h:9000
      token: t
      models: [{id: m1, task: ocr, kind: opensource, runner: paddle}]
"""

GATEWAY = """
host_discovery:
  source: gateway
  url: http://gateway:8080/v1/discovery/hosts
  refresh_s: 15
  fallback_static:
    - name: du-phong
      url: http://d:9000
      models: [{id: m1, task: ocr, kind: opensource, runner: paddle}]
"""


def _settings(tmp_path: Path, body: str) -> OcrSettings:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return OcrSettings(service_name="ocr", hosts_path=path)


def test_static_source_builds_a_static_registry(tmp_path):
    registry = build_host_registry(_settings(tmp_path, STATIC))
    assert isinstance(registry, StaticHostRegistry)


def test_gateway_source_builds_a_discovery_registry(tmp_path):
    registry = build_host_registry(_settings(tmp_path, GATEWAY))
    assert isinstance(registry, DiscoveryHostRegistry)


async def test_gateway_registry_keeps_the_static_list_as_fallback(tmp_path):
    # Gateway chưa lên lúc service khởi động không được làm service vô dụng.
    registry = build_host_registry(_settings(tmp_path, GATEWAY))
    assert (await registry.pick("m1")).name == "du-phong"
    await registry.aclose()


def test_gateway_source_without_url_falls_back_to_static(tmp_path):
    body = GATEWAY.replace("  url: http://gateway:8080/v1/discovery/hosts\n", "")
    registry = build_host_registry(_settings(tmp_path, body))
    assert isinstance(registry, StaticHostRegistry)


def test_missing_config_file_gives_an_empty_static_registry(tmp_path):
    settings = OcrSettings(service_name="ocr", hosts_path=tmp_path / "khong-co.yaml")
    registry = build_host_registry(settings)
    assert isinstance(registry, StaticHostRegistry)
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest services/ocr/tests/test_settings.py -v`
Mong đợi: FAIL với `ImportError: cannot import name 'build_host_registry'`

- [ ] **Step 3: Viết build_host_registry**

Thêm vào `services/ocr/src/ocr_service/settings.py`:
```python
def build_host_registry(settings: OcrSettings):
    """Dựng registry theo `host_discovery.source`.

    Đây là toàn bộ chi phí của việc chuyển từ danh sách tĩnh sang discovery
    động: một dòng trong config, không dòng nào trong logic service.
    """
    if not settings.hosts_path.is_file():
        return StaticHostRegistry([])
    parsed = HostsFile.model_validate(
        yaml.safe_load(settings.hosts_path.read_text(encoding="utf-8"))
    )
    discovery = parsed.host_discovery
    if discovery.source == "gateway" and discovery.url:
        return DiscoveryHostRegistry(
            discovery.url,
            refresh_s=discovery.refresh_s,
            fallback=discovery.fallback_static,
        )
    # source=gateway mà thiếu url là cấu hình sai; rơi về static còn hơn ném
    # lúc khởi động và làm service không lên được.
    return StaticHostRegistry(discovery.fallback_static)
```
Giữ `load_hosts` cũ để không phá test hiện có.

- [ ] **Step 4: Dùng nó ở main.py và worker.py**

Trong `services/ocr/src/ocr_service/main.py` `build_app()` và
`services/ocr/src/ocr_service/worker.py` `main()`, thay
`StaticHostRegistry(load_hosts(settings.hosts_path))` bằng
`build_host_registry(settings)`.

- [ ] **Step 5: Đổi config sang gateway**

`services/ocr/config.yaml`:
```yaml
host_discovery:
  source: gateway
  url: http://gateway:8080/v1/discovery/hosts
  refresh_s: 15
  # Giữ lại để service vẫn chạy được khi gateway chưa lên. Bỏ trống cũng được.
  fallback_static: []
```
Làm tương tự cho `services/asr/config.yaml` và `services/_template/config.yaml`.

- [ ] **Step 6: Chạy test**

```bash
uv run pytest services -v
./scripts/new-service.sh probedisc asr 8092 && uv run pytest services/probedisc -q
rm -rf services/probedisc && git checkout -- pyproject.toml uv.lock && uv sync
```
Mong đợi: tất cả PASS.

- [ ] **Step 7: Commit**

```bash
uv run ruff check . --fix
git add services
git commit -m "feat(services): lấy danh sách host từ gateway thay vì file tĩnh"
```

---

### Task 9: Registry service và `GET /v1/services`

**Files:**
- Create: `apps/gateway/config/services.yaml`
- Create: `apps/gateway/src/gateway/registry/services.py`
- Create: `apps/gateway/src/gateway/api/services.py`
- Test: `apps/gateway/tests/test_service_registry.py`

**Interfaces:**
- Consumes: `vypq_contracts.gateway.{ServiceInfo, ServiceState, ServicesResponse}`
- Produces:
  - `ServiceEntry(name: str, base_url: str)` và `load_services(path) -> list[ServiceEntry]`
  - `ServiceRegistry(entries, poll_timeout_s=10.0)` — `await refresh() -> None`, `states() -> list[ServiceState]`, `get(name) -> ServiceState | None`
  - `build_services_router(registry) -> APIRouter` với `GET /v1/services`

- [ ] **Step 1: Viết test trước**

`apps/gateway/tests/test_service_registry.py`:
```python
import httpx
import respx

from gateway.registry.services import ServiceEntry, ServiceRegistry
from vypq_contracts.common import HealthStatus

INFO_BODY = {
    "name": "ocr", "task": "ocr", "capability_input": "image",
    "capability_output": "text_boxes", "version": "0.1.0",
    "invoke_path": "/v1/ocr", "default_model": "m1",
}


def _registry(*entries: ServiceEntry) -> ServiceRegistry:
    return ServiceRegistry(list(entries))


@respx.mock
async def test_refresh_reads_info_and_health():
    respx.get("http://ocr:8001/v1/info").mock(return_value=httpx.Response(200, json=INFO_BODY))
    respx.get("http://ocr:8001/ready").mock(return_value=httpx.Response(200, json={
        "status": "ok", "service": "ocr", "version": "0.1.0", "detail": {}}))
    reg = _registry(ServiceEntry(name="ocr", base_url="http://ocr:8001"))
    await reg.refresh()
    state = reg.get("ocr")
    assert state.status is HealthStatus.OK
    assert state.info.invoke_path == "/v1/ocr"
    await reg.aclose()


@respx.mock
async def test_degraded_ready_is_reported_not_hidden():
    # /ready trả 503 nghĩa là service còn sống nhưng upstream của nó có vấn đề.
    # Giấu đi thì dashboard báo xanh trong khi request đang hỏng.
    respx.get("http://ocr:8001/v1/info").mock(return_value=httpx.Response(200, json=INFO_BODY))
    respx.get("http://ocr:8001/ready").mock(return_value=httpx.Response(503, json={
        "status": "degraded", "service": "ocr", "version": "0.1.0",
        "detail": {"model_host": "circuit đang mở"}}))
    reg = _registry(ServiceEntry(name="ocr", base_url="http://ocr:8001"))
    await reg.refresh()
    assert reg.get("ocr").status is HealthStatus.DEGRADED
    await reg.aclose()


@respx.mock
async def test_unreachable_service_is_down_but_still_listed():
    respx.get("http://ocr:8001/v1/info").mock(side_effect=httpx.ConnectError("chết"))
    reg = _registry(ServiceEntry(name="ocr", base_url="http://ocr:8001"))
    await reg.refresh()
    state = reg.get("ocr")
    assert state.status is HealthStatus.DOWN
    assert state.info.name == "ocr"        # vẫn liệt kê để biết nó tồn tại
    await reg.aclose()


@respx.mock
async def test_one_dead_service_does_not_stop_the_others():
    respx.get("http://a:8001/v1/info").mock(side_effect=httpx.ConnectError("chết"))
    respx.get("http://b:8002/v1/info").mock(return_value=httpx.Response(200, json=INFO_BODY))
    respx.get("http://b:8002/ready").mock(return_value=httpx.Response(200, json={
        "status": "ok", "service": "ocr", "version": "0.1.0", "detail": {}}))
    reg = _registry(
        ServiceEntry(name="a", base_url="http://a:8001"),
        ServiceEntry(name="b", base_url="http://b:8002"),
    )
    await reg.refresh()
    assert reg.get("a").status is HealthStatus.DOWN
    assert reg.get("b").status is HealthStatus.OK
    await reg.aclose()


@respx.mock
async def test_previous_info_is_kept_when_a_refresh_fails():
    # Một lần refresh trượt không được xoá mất hiểu biết về service.
    respx.get("http://ocr:8001/v1/info").mock(
        side_effect=[httpx.Response(200, json=INFO_BODY), httpx.ConnectError("chết")]
    )
    respx.get("http://ocr:8001/ready").mock(return_value=httpx.Response(200, json={
        "status": "ok", "service": "ocr", "version": "0.1.0", "detail": {}}))
    reg = _registry(ServiceEntry(name="ocr", base_url="http://ocr:8001"))
    await reg.refresh()
    await reg.refresh()
    state = reg.get("ocr")
    assert state.status is HealthStatus.DOWN
    assert state.info.invoke_path == "/v1/ocr"   # vẫn nhớ đường gọi
    await reg.aclose()


def test_get_unknown_service_returns_none():
    assert _registry().get("khong-co") is None
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/gateway/tests/test_service_registry.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'gateway.registry.services'`

- [ ] **Step 3: Viết registry/services.py**

`apps/gateway/src/gateway/registry/services.py`:
```python
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel, Field

from vypq_contracts.common import HealthStatus, Task
from vypq_contracts.gateway import ServiceInfo, ServiceState
from vypq_core.logging import get_logger

log = get_logger(__name__)


class ServiceEntry(BaseModel):
    name: str
    base_url: str


class ServicesFile(BaseModel):
    services: list[ServiceEntry] = Field(default_factory=list)


def load_services(path: Path) -> list[ServiceEntry]:
    if not path.is_file():
        return []
    return ServicesFile.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    ).services


def _placeholder(entry: ServiceEntry) -> ServiceState:
    return ServiceState(
        info=ServiceInfo(
            name=entry.name, task=Task.OCR, capability_input="unknown",
            capability_output="unknown", version="unknown", invoke_path="/v1/unknown",
        ),
        base_url=entry.base_url,
        status=HealthStatus.DOWN,
    )


class ServiceRegistry:
    """Biết những service nào tồn tại, chúng làm được gì, và có sống không."""

    def __init__(self, entries: list[ServiceEntry], poll_timeout_s: float = 10.0) -> None:
        self._entries = entries
        self._timeout = poll_timeout_s
        self._states: dict[str, ServiceState] = {e.name: _placeholder(e) for e in entries}
        self._client = httpx.AsyncClient(timeout=poll_timeout_s)

    def states(self) -> list[ServiceState]:
        return [self._states[e.name] for e in self._entries]

    def get(self, name: str) -> ServiceState | None:
        return self._states.get(name)

    async def refresh(self) -> None:
        await asyncio.gather(*(self._refresh_one(e) for e in self._entries))

    async def _refresh_one(self, entry: ServiceEntry) -> None:
        base = entry.base_url.rstrip("/")
        previous = self._states[entry.name]
        try:
            info_resp = await self._client.get(f"{base}/v1/info")
            info_resp.raise_for_status()
            info = ServiceInfo.model_validate(info_resp.json())
        except Exception as exc:
            # Giữ lại hiểu biết cũ: một lần refresh trượt không được xoá mất
            # đường gọi đã biết, nếu không request kế tiếp không biết POST đi đâu.
            log.warning("service_info_failed", service=entry.name, error=str(exc))
            self._states[entry.name] = previous.model_copy(
                update={"status": HealthStatus.DOWN}
            )
            return

        status = HealthStatus.DOWN
        try:
            ready = await self._client.get(f"{base}/ready")
            status = HealthStatus(ready.json().get("status", HealthStatus.DOWN))
        except Exception as exc:
            log.warning("service_ready_failed", service=entry.name, error=str(exc))

        self._states[entry.name] = ServiceState(
            info=info, base_url=entry.base_url, status=status,
            last_seen_at=datetime.now(UTC),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Viết api/services.py và config**

`apps/gateway/src/gateway/api/services.py`:
```python
from fastapi import APIRouter

from gateway.registry.services import ServiceRegistry
from vypq_contracts.gateway import ServicesResponse


def build_services_router(registry: ServiceRegistry) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/services", response_model=ServicesResponse)
    async def list_services() -> ServicesResponse:
        return ServicesResponse(services=registry.states())

    return router
```

`apps/gateway/config/services.yaml`:
```yaml
services:
  - {name: ocr, base_url: http://localhost:8001}
  - {name: asr, base_url: http://localhost:8002}
```

- [ ] **Step 5: Chạy test và commit**

```bash
uv run pytest apps/gateway -v
uv run ruff check . --fix
git add apps/gateway
git commit -m "feat(gateway): registry service, đọc /v1/info và /ready"
```
Mong đợi: tất cả PASS.

---
### Task 10: `RunRepo` — ghi lịch sử, chống trùng

**Files:**
- Modify: `apps/gateway/src/gateway/db/repo.py`
- Test: `apps/gateway/tests/test_run_repo.py`

**Interfaces:**
- Consumes: model `Run` từ Task 3
- Produces: `RunRepo(session)` — `await record(...) -> RunRecord`, `await list_runs(trace_id=None, service=None, status=None, limit=50, offset=0) -> tuple[list[RunRecord], int]`, `await get(run_id) -> RunRecord | None`

**Vì sao khoá duy nhất là `(trace_id, model_version)`:** Kafka giao ít nhất một
lần, nên cùng một kết quả có thể tới hai lần. Nhưng shadow-run cố tình cho nhiều
model cùng xử lý một event, nên `trace_id` một mình không đủ làm khoá — mỗi model
version là một dòng hợp lệ. `model_version` lưu chuỗi rỗng chứ không NULL, vì SQL
coi mọi NULL là khác nhau và khoá duy nhất sẽ không chặn được gì.

- [ ] **Step 1: Viết test trước**

`apps/gateway/tests/test_run_repo.py`:
```python
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import Base
from gateway.db.repo import RunRepo
from vypq_contracts.gateway import InvokeMode, RunStatus


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _record(repo, trace_id="t1", model="m1", status=RunStatus.OK, service="ocr"):
    return await repo.record(
        trace_id=trace_id, service=service, model_version=model,
        mode=InvokeMode.SYNC, status=status, input_uri="s3://b/a.jpg",
        output={"full_text": "xin chào"}, latency_ms=42, error=None,
    )


async def test_record_then_read_back(session):
    repo = RunRepo(session)
    run = await _record(repo)
    assert run.status is RunStatus.OK
    assert (await repo.get(run.id)).output["full_text"] == "xin chào"


async def test_same_trace_and_model_twice_is_recorded_once(session):
    # Kafka giao ít nhất một lần: cùng kết quả có thể tới hai lần.
    repo = RunRepo(session)
    first = await _record(repo)
    second = await _record(repo)
    assert first.id == second.id
    runs, total = await repo.list_runs()
    assert total == 1


async def test_same_trace_different_models_are_separate_runs(session):
    # Shadow-run: cùng một event, nhiều model version cùng xử lý.
    repo = RunRepo(session)
    await _record(repo, model="paddle-v4")
    await _record(repo, model="vietocr-ft")
    runs, total = await repo.list_runs()
    assert total == 2
    assert {r.model_version for r in runs} == {"paddle-v4", "vietocr-ft"}


async def test_empty_model_version_still_deduplicates(session):
    # NULL sẽ vô hiệu khoá duy nhất; chuỗi rỗng thì không.
    repo = RunRepo(session)
    await _record(repo, model="")
    await _record(repo, model="")
    _runs, total = await repo.list_runs()
    assert total == 1


async def test_filter_by_trace_id_finds_every_model_version(session):
    # Người gọi async chỉ cầm trace_id. Shadow-run cho nhiều model cùng xử lý,
    # nên một trace_id phải tra ra đủ các dòng của nó.
    repo = RunRepo(session)
    await _record(repo, trace_id="t-chung", model="paddle-v4")
    await _record(repo, trace_id="t-chung", model="vietocr-ft")
    await _record(repo, trace_id="t-khac", model="paddle-v4")
    runs, total = await repo.list_runs(trace_id="t-chung")
    assert total == 2
    assert {r.model_version for r in runs} == {"paddle-v4", "vietocr-ft"}


async def test_filter_by_service_and_status(session):
    repo = RunRepo(session)
    await _record(repo, trace_id="t1", service="ocr", status=RunStatus.OK)
    await _record(repo, trace_id="t2", service="ocr", status=RunStatus.FAILED)
    await _record(repo, trace_id="t3", service="asr", status=RunStatus.OK)

    _runs, total = await repo.list_runs(service="ocr")
    assert total == 2
    runs, total = await repo.list_runs(service="ocr", status=RunStatus.FAILED)
    assert total == 1
    assert runs[0].trace_id == "t2"


async def test_pagination_reports_total_not_page_size(session):
    repo = RunRepo(session)
    for i in range(7):
        await _record(repo, trace_id=f"t{i}")
    runs, total = await repo.list_runs(limit=3)
    assert len(runs) == 3
    assert total == 7


async def test_newest_run_comes_first(session):
    repo = RunRepo(session)
    await _record(repo, trace_id="cu")
    await _record(repo, trace_id="moi")
    runs, _total = await repo.list_runs()
    assert runs[0].trace_id == "moi"


async def test_failed_run_keeps_the_error_and_has_no_output(session):
    repo = RunRepo(session)
    run = await RunRepo(session).record(
        trace_id="t9", service="ocr", model_version="m1", mode=InvokeMode.ASYNC,
        status=RunStatus.FAILED, input_uri=None, output=None, latency_ms=None,
        error="gpu chết",
    )
    assert run.error == "gpu chết"
    assert run.output is None
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/gateway/tests/test_run_repo.py -v`
Mong đợi: FAIL với `ImportError: cannot import name 'RunRepo'`

- [ ] **Step 3: Viết RunRepo**

Thêm vào `apps/gateway/src/gateway/db/repo.py`:
```python
import uuid

from sqlalchemy import func

from gateway.db.models import Run
from vypq_contracts.gateway import InvokeMode, RunRecord, RunStatus


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
    ) -> RunRecord:
        key = model_version or ""
        existing = (
            await self._s.execute(
                select(Run).where(Run.trace_id == trace_id, Run.model_version == key)
            )
        ).scalar_one_or_none()
        if existing is not None:
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
        await self._s.commit()
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
```

- [ ] **Step 4: Chạy test và commit**

```bash
uv run pytest apps/gateway -v
uv run ruff check . --fix
git add apps/gateway
git commit -m "feat(gateway): RunRepo ghi lịch sử, khoá duy nhất theo trace và model"
```
Mong đợi: 8 test mới PASS.

---

### Task 11: `POST /v1/invoke` đường sync

**Files:**
- Create: `apps/gateway/src/gateway/proxy.py`, `apps/gateway/src/gateway/api/invoke.py`
- Test: `apps/gateway/tests/test_invoke_sync.py`

**Interfaces:**
- Consumes: `ServiceRegistry`, `RunRepo`, `vypq_core.http_client.UpstreamClient`
- Produces:
  - `SyncProxy(registry, session_factory, timeout_s: float = 120.0)` — `await invoke(service, data, filename, model_version, trace_id=None) -> RunRecord`, `await fetch(uri) -> bytes`, `await aclose()`
  - `build_invoke_router(proxy, dispatcher=None) -> APIRouter` với `POST /v1/invoke/upload` (multipart) và `POST /v1/invoke` (JSON, có `input_uri`)

Gateway **luôn** gửi multipart tới service, kể cả khi nhận `input_uri` — service
chỉ có một đường vào là multipart, và tự tải URI là việc của worker.

- [ ] **Step 1: Viết test trước**

`apps/gateway/tests/test_invoke_sync.py`:
```python
import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.api.invoke import build_invoke_router
from gateway.db.models import Base
from gateway.db.repo import RunRepo
from gateway.main import build_app
from gateway.proxy import SyncProxy
from gateway.registry.services import ServiceEntry, ServiceRegistry
from gateway.settings import GatewaySettings
from vypq_contracts.common import HealthStatus, Task
from vypq_contracts.gateway import RunStatus, ServiceInfo, ServiceState

OCR_RESULT = {
    "trace_id": "t1", "model_version": "m1", "latency_ms": 12,
    "result": {"full_text": "xin chào", "boxes": []},
}


def _state(status=HealthStatus.OK) -> ServiceState:
    return ServiceState(
        info=ServiceInfo(
            name="ocr", task=Task.OCR, capability_input="image",
            capability_output="text_boxes", version="0.1.0",
            invoke_path="/v1/ocr", default_model="m1",
        ),
        base_url="http://ocr:8001",
        status=status,
    )


@pytest.fixture
async def ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = ServiceRegistry([ServiceEntry(name="ocr", base_url="http://ocr:8001")])
    registry._states["ocr"] = _state()
    proxy = SyncProxy(registry, factory)
    app = build_app(factory, GatewaySettings(service_name="gateway"),
                    routers=[build_invoke_router(proxy)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c, factory, registry
    await registry.aclose()
    await proxy.aclose()
    await engine.dispose()


@respx.mock
async def test_upload_reaches_the_service_and_returns_its_result(ctx):
    client, _factory, _reg = ctx
    route = respx.post("http://ocr:8001/v1/ocr").mock(
        return_value=httpx.Response(200, json=OCR_RESULT)
    )
    resp = await client.post(
        "/v1/invoke/upload",
        data={"service": "ocr"},
        files={"file": ("a.png", b"\x89PNG", "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["full_text"] == "xin chào"
    assert route.called


@respx.mock
async def test_every_invocation_is_recorded(ctx):
    client, factory, _reg = ctx
    respx.post("http://ocr:8001/v1/ocr").mock(return_value=httpx.Response(200, json=OCR_RESULT))
    await client.post(
        "/v1/invoke/upload", data={"service": "ocr"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    async with factory() as s:
        runs, total = await RunRepo(s).list_runs()
    assert total == 1
    assert runs[0].status is RunStatus.OK
    assert runs[0].service == "ocr"
    assert runs[0].latency_ms is not None


@respx.mock
async def test_service_failure_is_recorded_as_failed_not_dropped(ctx):
    # Lỗi vẫn phải vào lịch sử — đó là lúc người ta cần lịch sử nhất.
    client, factory, _reg = ctx
    respx.post("http://ocr:8001/v1/ocr").mock(
        return_value=httpx.Response(503, json={"code": "upstream_error", "message": "gpu chết"})
    )
    resp = await client.post(
        "/v1/invoke/upload", data={"service": "ocr"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    assert resp.status_code >= 400
    async with factory() as s:
        runs, total = await RunRepo(s).list_runs()
    assert total == 1
    assert runs[0].status is RunStatus.FAILED
    assert runs[0].error


async def test_unknown_service_is_404(ctx):
    client, _factory, _reg = ctx
    resp = await client.post(
        "/v1/invoke/upload", data={"service": "khong-co"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    assert resp.status_code == 404


async def test_down_service_is_refused_before_sending_anything(ctx):
    # Không gửi request vào một service đã biết là chết: 503 ngay, rõ lý do.
    client, _factory, registry = ctx
    registry._states["ocr"] = _state(HealthStatus.DOWN)
    resp = await client.post(
        "/v1/invoke/upload", data={"service": "ocr"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    assert resp.status_code == 503


@respx.mock
async def test_model_version_is_forwarded_to_the_service(ctx):
    client, _factory, _reg = ctx
    captured = {}

    def _record(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json=OCR_RESULT)

    respx.post("http://ocr:8001/v1/ocr").mock(side_effect=_record)
    await client.post(
        "/v1/invoke/upload",
        data={"service": "ocr", "model_version": "vietocr-ft"},
        files={"file": ("a.png", b"x", "image/png")},
    )
    assert b"vietocr-ft" in captured["body"]


@respx.mock
async def test_input_uri_is_fetched_then_forwarded_as_multipart(ctx):
    # Service chỉ có một đường vào là multipart; tự tải URI là việc của worker.
    client, _factory, _reg = ctx
    respx.get("http://minio/a.png").mock(return_value=httpx.Response(200, content=b"\x89PNG"))
    route = respx.post("http://ocr:8001/v1/ocr").mock(
        return_value=httpx.Response(200, json=OCR_RESULT)
    )
    resp = await client.post(
        "/v1/invoke", json={"service": "ocr", "input_uri": "http://minio/a.png"}
    )
    assert resp.status_code == 200
    assert route.called
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/gateway/tests/test_invoke_sync.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'gateway.proxy'`

- [ ] **Step 3: Viết proxy.py**

`apps/gateway/src/gateway/proxy.py`:
```python
import time
import uuid

import httpx

from gateway.db.repo import RunRepo
from gateway.registry.services import ServiceRegistry
from vypq_contracts.common import ErrorCode, HealthStatus
from vypq_contracts.gateway import InvokeMode, RunRecord, RunStatus
from vypq_core.errors import ServiceError
from vypq_core.logging import get_logger

log = get_logger(__name__)


class SyncProxy:
    """Chuyển tiếp request tới service và ghi lại mọi lần chạy."""

    def __init__(self, registry: ServiceRegistry, session_factory, timeout_s: float = 120.0):
        self._registry = registry
        self._factory = session_factory
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def fetch(self, uri: str) -> bytes:
        try:
            response = await self._client.get(uri)
        except (httpx.UnsupportedProtocol, httpx.InvalidURL) as exc:
            # PHẢI bắt TRƯỚC TransportError: UnsupportedProtocol kế thừa từ nó.
            # URI sai scheme hay sai định dạng thì thử lại bao nhiêu lần cũng
            # hỏng y hệt — xếp vào hạ tầng sẽ làm consumer pause vô hạn và kẹt
            # cả partition sau một URI hỏng, trong khi DLQ vẫn rỗng.
            raise ServiceError(
                ErrorCode.BAD_INPUT, f"URI không dùng được: {uri} ({exc})", 422
            ) from exc
        if response.status_code >= 400:
            raise ServiceError(
                ErrorCode.BAD_INPUT, f"tải {uri} thất bại ({response.status_code})", 422
            )
        return response.content

    async def invoke(
        self, service: str, data: bytes, filename: str,
        model_version: str | None, trace_id: str | None = None,
    ) -> RunRecord:
        state = self._registry.get(service)
        if state is None:
            raise ServiceError(ErrorCode.BAD_INPUT, f"không có service '{service}'", 404)
        if state.info is None:
            # Chưa poll được lần nào nên chưa biết invoke_path. Đoán đường gọi là
            # gửi request vào hư không rồi báo lỗi ở chỗ chẳng liên quan.
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE,
                f"gateway chưa liên hệ được '{service}' lần nào, chưa biết đường gọi",
                503,
            )
        if state.status is HealthStatus.DOWN:
            # Đã biết nó chết thì đừng gửi vào: trả 503 ngay, nói rõ lý do,
            # thay vì để caller chờ hết timeout rồi nhận lỗi mơ hồ.
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE, f"service '{service}' đang không phản hồi", 503
            )

        trace = trace_id or uuid.uuid4().hex
        url = f"{state.base_url.rstrip('/')}{state.info.invoke_path}"
        form = {"model_version": model_version} if model_version else {}
        started = time.monotonic()
        status, output, error, resolved = RunStatus.FAILED, None, None, model_version
        try:
            response = await self._client.post(
                url,
                data=form,
                files={"file": (filename, data, "application/octet-stream")},
                headers={"x-trace-id": trace},
            )
            if response.status_code >= 400:
                error = f"service trả {response.status_code}: {response.text[:200]}"
            else:
                body = response.json()
                output = body.get("result")
                resolved = body.get("model_version") or model_version
                status = RunStatus.OK
        except Exception as exc:
            error = str(exc)

        latency_ms = int((time.monotonic() - started) * 1000)
        async with self._factory() as session:
            record = await RunRepo(session).record(
                trace_id=trace, service=service, model_version=resolved,
                mode=InvokeMode.SYNC, status=status, input_uri=None,
                output=output, latency_ms=latency_ms, error=error,
            )
        if status is RunStatus.FAILED:
            # Ghi xong rồi mới ném: lỗi là lúc lịch sử có giá trị nhất.
            raise ServiceError(ErrorCode.UPSTREAM_ERROR, error or "service lỗi", 502)
        return record

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Viết api/invoke.py**

`apps/gateway/src/gateway/api/invoke.py`:
```python
import uuid

from fastapi import APIRouter, File, Form, UploadFile

from gateway.proxy import SyncProxy
from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import InvokeMode, InvokeRequest, InvokeResponse
from vypq_core.errors import ServiceError


def build_invoke_router(proxy: SyncProxy, dispatcher=None) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.post("/invoke/upload", response_model=InvokeResponse)
    async def invoke_upload(
        service: str = Form(...),
        model_version: str | None = Form(default=None),
        file: UploadFile = File(...),
    ) -> InvokeResponse:
        record = await proxy.invoke(
            service, await file.read(), file.filename or "input", model_version
        )
        return InvokeResponse(
            trace_id=record.trace_id, mode=InvokeMode.SYNC,
            run_id=record.id, result=record.output,
        )

    @router.post("/invoke", response_model=InvokeResponse)
    async def invoke(request: InvokeRequest) -> InvokeResponse:
        if not request.input_uri:
            raise ServiceError(ErrorCode.BAD_INPUT, "thiếu input_uri", 422)
        if request.mode is InvokeMode.ASYNC:
            if dispatcher is None:
                raise ServiceError(
                    ErrorCode.BAD_INPUT, "gateway này chưa bật đường async", 501
                )
            trace = uuid.uuid4().hex
            await dispatcher.dispatch(request, trace)
            return InvokeResponse(trace_id=trace, mode=InvokeMode.ASYNC)

        data = await proxy.fetch(request.input_uri)
        record = await proxy.invoke(
            request.service, data, "input", request.model_version
        )
        return InvokeResponse(
            trace_id=record.trace_id, mode=InvokeMode.SYNC,
            run_id=record.id, result=record.output,
        )

    return router
```

- [ ] **Step 5: Chạy test và commit**

```bash
uv run pytest apps/gateway -v
uv run ruff check . --fix
git add apps/gateway
git commit -m "feat(gateway): đường sync chuyển tiếp tới service và ghi lịch sử"
```
Mong đợi: 7 test mới PASS.

---
### Task 12: Đường async — đẩy vào Kafka

**Files:**
- Create: `apps/gateway/src/gateway/dispatcher.py`
- Test: `apps/gateway/tests/test_dispatcher.py`

**Interfaces:**
- Consumes: `vypq_events.producer.EventProducer`, `vypq_events.topics.request_topic`, `ServiceRegistry`
- Produces: `Dispatcher(registry, producer)` — `await dispatch(request: InvokeRequest, trace_id: str) -> None`

Gateway **không** tạo dòng `runs` lúc đẩy. Kết quả có thể về từ nhiều model
version (shadow-run), mỗi cái là một dòng riêng — dựng sẵn một dòng rỗng sẽ
không biết gán cho model nào. Result consumer ở Task 13 mới ghi.

- [ ] **Step 1: Viết test trước**

`apps/gateway/tests/test_dispatcher.py`:
```python
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
        info=ServiceInfo(
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
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/gateway/tests/test_dispatcher.py -v`
Mong đợi: FAIL với `ModuleNotFoundError: No module named 'gateway.dispatcher'`

- [ ] **Step 3: Viết dispatcher.py**

`apps/gateway/src/gateway/dispatcher.py`:
```python
from gateway.registry.services import ServiceRegistry
from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import InvokeRequest
from vypq_core.errors import ServiceError
from vypq_events.envelope import EventEnvelope
from vypq_events.schemas.inference import InferenceRequested
from vypq_events.topics import request_topic


class Dispatcher:
    """Đẩy request vào Kafka cho worker xử lý.

    KHÔNG tạo dòng `runs` ở đây: shadow-run cho nhiều model version cùng xử lý
    một event, nên chưa biết sẽ có bao nhiêu kết quả và mỗi cái thuộc model nào.
    Result consumer ghi khi kết quả thực sự về.
    """

    def __init__(self, registry: ServiceRegistry, producer) -> None:
        self._registry = registry
        self._producer = producer

    async def dispatch(self, request: InvokeRequest, trace_id: str) -> None:
        state = self._registry.get(request.service)
        if state is None:
            raise ServiceError(
                ErrorCode.BAD_INPUT, f"không có service '{request.service}'", 404
            )
        if state.info is None:
            # KHÔNG đoán task. Topic chọn theo task; đoán sai là đẩy việc sang
            # hàng đợi của service khác, im lặng, trong khi người gọi đã cầm
            # trace_id và tin rằng việc đã được nhận.
            raise ServiceError(
                ErrorCode.MODEL_UNAVAILABLE,
                f"gateway chưa liên hệ được '{request.service}' lần nào, chưa biết task",
                503,
            )
        if not request.input_uri:
            raise ServiceError(ErrorCode.BAD_INPUT, "đường async cần input_uri", 422)

        # Không kiểm status: khác đường sync, message nằm trong topic chờ service
        # sống lại. Từ chối ở đây là vứt việc đi vì một sự cố tạm thời.
        payload = InferenceRequested(
            task=state.info.task,
            input_uri=request.input_uri,
            model_version=request.model_version,
        )
        envelope = EventEnvelope[InferenceRequested].new(
            "inference.requested", payload, trace_id=trace_id
        )
        await self._producer.publish(
            request_topic(state.info.task), envelope, key=trace_id
        )
```

- [ ] **Step 4: Chạy test và commit**

```bash
uv run pytest apps/gateway -v
uv run ruff check . --fix
git add apps/gateway
git commit -m "feat(gateway): đường async đẩy request vào Kafka"
```

---

### Task 13: Result consumer và `GET /v1/runs`

**Files:**
- Create: `apps/gateway/src/gateway/result_consumer.py`, `apps/gateway/src/gateway/api/runs.py`
- Test: `apps/gateway/tests/test_result_consumer.py`, `apps/gateway/tests/test_runs_api.py`

**Interfaces:**
- Consumes: `vypq_events.consumer.EventConsumer`, `RunRepo`
- Produces:
  - `make_result_handler(session_factory, service_name_for) -> Callable[[RawEnvelope], Awaitable[None]]`
  - `build_result_consumers(session_factory, settings, producer, registry) -> list[EventConsumer]`
  - `build_runs_router(session_factory) -> APIRouter` với `GET /v1/runs`, `GET /v1/runs/{run_id}`

- [ ] **Step 1: Viết test cho result handler**

`apps/gateway/tests/test_result_consumer.py`:
```python
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import Base
from gateway.db.repo import RunRepo
from gateway.result_consumer import make_result_handler
from vypq_contracts.common import Task
from vypq_contracts.gateway import RunStatus
from vypq_events.envelope import EventEnvelope, RawEnvelope
from vypq_events.schemas.inference import InferenceCompleted


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _completed(model="m1", trace="t1") -> RawEnvelope:
    env = EventEnvelope[InferenceCompleted].new(
        "inference.completed",
        InferenceCompleted(
            task=Task.OCR, model_version=model, input_uri="s3://b/a.jpg",
            output={"full_text": "xin chào"}, latency_ms=33,
        ),
        trace_id=trace,
    )
    return RawEnvelope.model_validate_json(env.model_dump_json())


async def test_result_is_written_to_runs(factory):
    handler = make_result_handler(factory, lambda task: "ocr")
    await handler(_completed())
    async with factory() as s:
        runs, total = await RunRepo(s).list_runs()
    assert total == 1
    assert runs[0].status is RunStatus.OK
    assert runs[0].output["full_text"] == "xin chào"
    assert runs[0].latency_ms == 33


async def test_duplicate_delivery_writes_one_row(factory):
    # Kafka giao ít nhất một lần; cùng (trace, model) là cùng một kết quả.
    handler = make_result_handler(factory, lambda task: "ocr")
    await handler(_completed())
    await handler(_completed())
    async with factory() as s:
        _runs, total = await RunRepo(s).list_runs()
    assert total == 1


async def test_shadow_run_results_are_separate_rows(factory):
    handler = make_result_handler(factory, lambda task: "ocr")
    await handler(_completed(model="paddle-v4"))
    await handler(_completed(model="vietocr-ft"))
    async with factory() as s:
        runs, total = await RunRepo(s).list_runs()
    assert total == 2
    assert {r.model_version for r in runs} == {"paddle-v4", "vietocr-ft"}


async def test_unparseable_payload_raises_so_the_consumer_dead_letters_it(factory):
    # Envelope hỏng là dữ liệu hỏng: phải ném để EventConsumer đẩy vào DLQ,
    # KHÔNG được nuốt — nuốt là mất kết quả mà không ai biết.
    handler = make_result_handler(factory, lambda task: "ocr")
    bad = RawEnvelope(
        event_id="e", event_type="inference.completed", trace_id="t",
        occurred_at="2026-08-18T00:00:00Z", payload={"khong": "dung shape"},
    )
    with pytest.raises(Exception):
        await handler(bad)
```

- [ ] **Step 2: Viết test cho API runs**

`apps/gateway/tests/test_runs_api.py`:
```python
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.api.runs import build_runs_router
from gateway.db.models import Base
from gateway.db.repo import RunRepo
from gateway.main import build_app
from gateway.settings import GatewaySettings
from vypq_contracts.gateway import InvokeMode, RunStatus


@pytest.fixture
async def ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = build_app(factory, GatewaySettings(service_name="gateway"),
                    routers=[build_runs_router(factory)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c, factory
    await engine.dispose()


async def _seed(factory, n=3, service="ocr", status=RunStatus.OK):
    async with factory() as s:
        for i in range(n):
            await RunRepo(s).record(
                trace_id=f"{service}-{status.value}-{i}", service=service,
                model_version="m1", mode=InvokeMode.SYNC, status=status,
                input_uri=None, output={"ok": True}, latency_ms=10, error=None,
            )


async def test_list_runs_returns_total_and_page(ctx):
    client, factory = ctx
    await _seed(factory, n=5)
    body = (await client.get("/v1/runs?limit=2")).json()
    assert body["total"] == 5
    assert len(body["runs"]) == 2


async def test_filter_by_service(ctx):
    client, factory = ctx
    await _seed(factory, n=2, service="ocr")
    await _seed(factory, n=3, service="asr")
    assert (await client.get("/v1/runs?service=asr")).json()["total"] == 3


async def test_filter_by_trace_id(ctx):
    # Đây là cách duy nhất người gọi async tìm lại kết quả của mình.
    client, factory = ctx
    await _seed(factory, n=2, service="ocr")
    body = (await client.get("/v1/runs?trace_id=ocr-ok-0")).json()
    assert body["total"] == 1


async def test_filter_by_status(ctx):
    client, factory = ctx
    await _seed(factory, n=2, status=RunStatus.OK)
    await _seed(factory, n=1, status=RunStatus.FAILED)
    assert (await client.get("/v1/runs?status=failed")).json()["total"] == 1


async def test_get_one_run(ctx):
    client, factory = ctx
    await _seed(factory, n=1)
    run_id = (await client.get("/v1/runs")).json()["runs"][0]["id"]
    assert (await client.get(f"/v1/runs/{run_id}")).status_code == 200


async def test_unknown_run_is_404(ctx):
    client, _factory = ctx
    assert (await client.get("/v1/runs/khong-co")).status_code == 404


async def test_invalid_status_filter_is_422(ctx):
    client, _factory = ctx
    assert (await client.get("/v1/runs?status=lung-tung")).status_code == 422
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/gateway/tests/test_result_consumer.py apps/gateway/tests/test_runs_api.py -v`
Mong đợi: FAIL với `ModuleNotFoundError`

- [ ] **Step 4: Viết result_consumer.py**

`apps/gateway/src/gateway/result_consumer.py`:
```python
from collections.abc import Callable

from gateway.db.repo import RunRepo
from gateway.settings import GatewaySettings
from vypq_contracts.common import Task
from vypq_contracts.gateway import InvokeMode, RunStatus
from vypq_events.consumer import EventConsumer
from vypq_events.envelope import RawEnvelope
from vypq_events.schemas.inference import InferenceCompleted
from vypq_events.topics import dlq_topic, result_topic


def make_result_handler(session_factory, service_name_for: Callable[[Task], str]):
    async def handle(envelope: RawEnvelope) -> None:
        # Không bọc try: envelope hỏng là dữ liệu hỏng, phải ném để
        # EventConsumer đẩy vào DLQ. Nuốt ở đây là mất kết quả mà không ai biết.
        completed = InferenceCompleted.model_validate(envelope.payload)
        async with session_factory() as session:
            await RunRepo(session).record(
                trace_id=envelope.trace_id,
                service=service_name_for(completed.task),
                model_version=completed.model_version,
                mode=InvokeMode.ASYNC,
                status=RunStatus.OK,
                input_uri=completed.input_uri,
                output=completed.output,
                latency_ms=completed.latency_ms,
                error=None,
            )

    return handle


def build_result_consumers(
    session_factory, settings: GatewaySettings, producer, registry
) -> list[EventConsumer]:
    def service_name_for(task: Task) -> str:
        for state in registry.states():
            if state.info.task is task:
                return state.info.name
        return task.value

    handler = make_result_handler(session_factory, service_name_for)
    return [
        EventConsumer(
            topic=result_topic(task),
            group_id="gateway-results",
            handler=handler,
            dlq_topic=dlq_topic(task),
            producer=producer,
            brokers=settings.brokers,
        )
        for task in (Task.OCR, Task.ASR)
    ]
```

- [ ] **Step 5: Viết api/runs.py**

`apps/gateway/src/gateway/api/runs.py`:
```python
from fastapi import APIRouter, Query

from gateway.db.repo import RunRepo
from vypq_contracts.common import ErrorCode
from vypq_contracts.gateway import RunRecord, RunsResponse, RunStatus
from vypq_core.errors import ServiceError


def build_runs_router(session_factory) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/runs", response_model=RunsResponse)
    async def list_runs(
        trace_id: str | None = None,
        service: str | None = None,
        status: RunStatus | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> RunsResponse:
        async with session_factory() as session:
            runs, total = await RunRepo(session).list_runs(
                trace_id=trace_id, service=service, status=status,
                limit=limit, offset=offset,
            )
        return RunsResponse(runs=runs, total=total)

    @router.get("/runs/{run_id}", response_model=RunRecord)
    async def get_run(run_id: str) -> RunRecord:
        async with session_factory() as session:
            run = await RunRepo(session).get(run_id)
        if run is None:
            raise ServiceError(ErrorCode.BAD_INPUT, f"không có run '{run_id}'", 404)
        return run

    return router
```

- [ ] **Step 6: Chạy test và commit**

```bash
uv run pytest apps/gateway -v
uv run ruff check . --fix
git add apps/gateway
git commit -m "feat(gateway): consume kết quả về DB và API tra cứu lịch sử"
```
Mong đợi: 10 test mới PASS.

---
### Task 14: Ghép thành gateway chạy được

**Files:**
- Modify: `apps/gateway/src/gateway/main.py`
- Create: `apps/gateway/Dockerfile`
- Modify: `infra/compose/docker-compose.dev.yml`
- Create: `scripts/smoke-gateway.sh`
- Test: `apps/gateway/tests/test_lifespan.py`

**Interfaces:**
- Consumes: mọi thứ từ Task 3–13
- Produces: `create_gateway() -> FastAPI` (đọc env, gắn đủ router, lifespan chạy poller + producer + result consumer), `app = create_gateway()`

- [ ] **Step 1: Viết test cho lifespan**

`apps/gateway/tests/test_lifespan.py`:
```python
import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import Base
from gateway.main import build_app
from gateway.settings import GatewaySettings


class SpyTask:
    def __init__(self) -> None:
        self.rounds = 0

    async def run(self) -> None:
        while True:
            self.rounds += 1
            await asyncio.sleep(0.01)


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_background_tasks_start_and_stop_with_the_app(factory):
    from gateway.main import background_lifespan

    spy = SpyTask()
    app = build_app(
        factory, GatewaySettings(service_name="gateway"),
        lifespan=background_lifespan([spy.run], on_shutdown=[]),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)
            assert (await client.get("/health")).status_code == 200
            assert spy.rounds > 0
    # Sau khi thoát lifespan, vòng nền phải bị huỷ chứ không chạy tiếp.
    stopped_at = spy.rounds
    await asyncio.sleep(0.05)
    assert spy.rounds == stopped_at


async def test_a_crashing_background_task_does_not_take_the_app_down(factory):
    from gateway.main import background_lifespan

    async def explode() -> None:
        raise RuntimeError("vòng nền chết")

    app = build_app(
        factory, GatewaySettings(service_name="gateway"),
        lifespan=background_lifespan([explode], on_shutdown=[]),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)
            # Poller chết không được kéo theo API: /health vẫn phải trả lời.
            assert (await client.get("/health")).status_code == 200


async def test_shutdown_hooks_run(factory):
    from gateway.main import background_lifespan

    closed = []

    async def close() -> None:
        closed.append(True)

    app = build_app(
        factory, GatewaySettings(service_name="gateway"),
        lifespan=background_lifespan([], on_shutdown=[close]),
    )
    async with app.router.lifespan_context(app):
        pass
    assert closed == [True]
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest apps/gateway/tests/test_lifespan.py -v`
Mong đợi: FAIL với `ImportError: cannot import name 'background_lifespan'`

- [ ] **Step 3: Viết background_lifespan và create_gateway**

Thêm vào `apps/gateway/src/gateway/main.py`:
```python
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

from vypq_core.logging import get_logger

log = get_logger(__name__)


def background_lifespan(
    tasks: Sequence[Callable[[], Awaitable[None]]],
    on_shutdown: Sequence[Callable[[], Awaitable[None]]],
):
    """Chạy các vòng nền suốt vòng đời app, huỷ sạch khi tắt."""

    @asynccontextmanager
    async def lifespan(_app):
        running = [asyncio.create_task(_guard(t)) for t in tasks]
        try:
            yield
        finally:
            for task in running:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)
            for hook in on_shutdown:
                await hook()

    return lifespan


async def _guard(task: Callable[[], Awaitable[None]]) -> None:
    # Vòng nền chết KHÔNG được kéo theo API. Poller hỏng thì host dần quá hạn
    # và biến mất khỏi định tuyến — đó là hỏng an toàn. API sập thì mất tất.
    try:
        await task()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("background_task_died", error=str(exc))


def create_gateway():
    from gateway.api.discovery import build_discovery_router
    from gateway.api.hosts import build_hosts_router
    from gateway.api.invoke import build_invoke_router
    from gateway.api.runs import build_runs_router
    from gateway.api.services import build_services_router
    from gateway.db.engine import make_engine, make_session_factory
    from gateway.dispatcher import Dispatcher
    from gateway.proxy import SyncProxy
    from gateway.registry.poller import HostPoller
    from gateway.registry.services import ServiceRegistry, load_services
    from gateway.result_consumer import build_result_consumers
    from gateway.settings import GatewaySettings
    from vypq_events.producer import EventProducer

    settings = GatewaySettings()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)

    service_registry = ServiceRegistry(load_services(settings.services_path))
    poller = HostPoller(factory, settings)
    producer = EventProducer(settings.brokers)
    proxy = SyncProxy(service_registry, factory)
    dispatcher = Dispatcher(service_registry, producer)
    consumers = build_result_consumers(factory, settings, producer, service_registry)

    async def refresh_services() -> None:
        while True:
            await service_registry.refresh()
            await asyncio.sleep(settings.poll_interval_s)

    async def run_consumers() -> None:
        await producer.start()
        for consumer in consumers:
            await consumer.start()
        await asyncio.gather(*(c.run() for c in consumers))

    async def shutdown() -> None:
        for consumer in consumers:
            await consumer.stop()
        await producer.stop()
        await service_registry.aclose()
        await proxy.aclose()
        await engine.dispose()

    return build_app(
        factory,
        settings,
        routers=[
            build_hosts_router(factory, settings),
            build_discovery_router(factory, settings),
            build_services_router(service_registry),
            build_invoke_router(proxy, dispatcher),
            build_runs_router(factory),
        ],
        lifespan=background_lifespan(
            [poller.run, refresh_services, run_consumers], on_shutdown=[shutdown]
        ),
    )


app = create_gateway()
```

- [ ] **Step 4: Dockerfile và compose**

`apps/gateway/Dockerfile`:
```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY packages ./packages
COPY apps/gateway ./apps/gateway
RUN uv sync --frozen --package gateway

ENV VYPQ_PORT=8080 VYPQ_SERVICES_PATH=/app/apps/gateway/config/services.yaml
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:8080/health || exit 1
CMD ["uv", "run", "uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Thêm service `gateway` vào `infra/compose/docker-compose.dev.yml`, phụ thuộc
`postgres` và `redpanda`, với `VYPQ_DATABASE_URL` và `VYPQ_BROKERS` trỏ vào chúng.

- [ ] **Step 5: Viết smoke test toàn stack**

`scripts/smoke-gateway.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
GW=${GW:-http://localhost:8080}

echo "== gateway sống =="
curl -fsS "$GW/health" >/dev/null

echo "== đăng ký host =="
curl -fsS -X POST "$GW/v1/hosts" -H 'Content-Type: application/json' \
  -d "{\"name\":\"gpu-dev\",\"url\":\"${HOST_URL:?dat HOST_URL}\",\"token\":\"${VYPQ_TOKEN:?dat VYPQ_TOKEN}\"}" >/dev/null

echo "== chờ poller thấy host =="
for _ in $(seq 1 20); do
  curl -fsS "$GW/v1/hosts" | grep -q '"healthy":true' && break
  sleep 2
done
curl -fsS "$GW/v1/hosts" | grep -q '"healthy":true'

echo "== discovery có token, listing thì không =="
curl -fsS "$GW/v1/discovery/hosts" | grep -q "$VYPQ_TOKEN"
! curl -fsS "$GW/v1/hosts" | grep -q "$VYPQ_TOKEN"

echo "== service tự khai capability =="
curl -fsS "$GW/v1/services" | grep -q '"invoke_path"'

echo "== gọi OCR qua gateway =="
curl -fsS -F service=ocr -F file=@tests/fixtures/sample.png "$GW/v1/invoke/upload" | grep -q full_text

echo "== lần chạy đó vào lịch sử =="
curl -fsS "$GW/v1/runs?limit=1" | grep -q '"status":"ok"'

echo "TẤT CẢ ĐẠT"
```

- [ ] **Step 6: Chạy toàn stack và smoke thật**

```bash
docker compose -f infra/compose/docker-compose.dev.yml up -d postgres redpanda
cd apps/gateway && VYPQ_DATABASE_URL=postgresql+asyncpg://vypq:vypq@localhost:5432/vypq \
  uv run alembic upgrade head && cd ../..
# model-host chế độ fake + ocr service + gateway, mỗi cái một terminal
chmod +x scripts/smoke-gateway.sh
HOST_URL=http://localhost:9001 VYPQ_TOKEN=sekret ./scripts/smoke-gateway.sh
```
Mong đợi: in ra `TẤT CẢ ĐẠT`. Ghi lại output thật vào báo cáo.

- [ ] **Step 7: Commit**

```bash
uv run ruff check . --fix
git add apps/gateway infra scripts
git commit -m "feat(gateway): ghép entrypoint, vòng nền và smoke test toàn stack"
```

---

### Task 15: Metrics và cảnh báo

Đây là điều kiện mà review tổng Plan A nêu rõ: **phải có metric và alert trên
`dlq_publish_failed` và `consumer_paused` trước khi chạy không người trông.**
DLQ hỏng vĩnh viễn sẽ kẹt cả partition, im lặng.

**Files:**
- Create: `packages/vypq-core/src/vypq_core/metrics.py`
- Modify: `packages/vypq-events/src/vypq_events/consumer.py` (đếm pause và DLQ)
- Modify: `apps/gateway/src/gateway/main.py` (gắn `/metrics`)
- Create: `infra/prometheus/prometheus.yml`, `infra/prometheus/alerts.yml`
- Test: bổ sung vào `packages/vypq-events/tests/test_consumer.py` (không tạo file mới)

**Interfaces:**
- Produces:
  - `vypq_core.metrics`: `EVENTS_PAUSED`, `EVENTS_DEAD_LETTERED`, `DLQ_PUBLISH_FAILED` (Counter, nhãn `topic`), `build_metrics_router() -> APIRouter` với `GET /metrics`
  - Prometheus scrape thêm `/public_metrics` của Redpanda để lấy consumer lag (spec bước 10)
  - `EventConsumer` tăng ba counter trên ở đúng ba chỗ

- [ ] **Step 1: Viết test trước**

Thêm vào CUỐI `packages/vypq-events/tests/test_consumer.py`. Đặt ở đây chứ không
tạo file mới: `--import-mode=importlib` không cho import chéo giữa các file test,
nên file mới sẽ phải chép lại nguyên khối `FakeConsumer`/`FakeProducer`/`_msg`/
`_consumer`/`TP` — hai bản chép tay sẽ trôi khỏi nhau. Các helper đó đã có sẵn ở
đầu file này.

```python
from prometheus_client import REGISTRY


def _value(name: str, topic: str) -> float:
    return REGISTRY.get_sample_value(name, {"topic": topic}) or 0.0


async def test_pausing_increments_the_paused_counter():
    async def handler(_env):
        raise UpstreamError("gpu chết")

    before = _value("vypq_events_consumer_paused_total", "infer.ocr.requests")
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0)]}])
    c = _consumer(kafka, FakeProducer(), handler, max_attempts=1)
    await c.run_once()
    assert _value("vypq_events_consumer_paused_total", "infer.ocr.requests") == before + 1


async def test_dead_lettering_increments_its_counter():
    async def handler(_env):
        raise ValueError("dữ liệu hỏng")

    before = _value("vypq_events_dead_lettered_total", "infer.ocr.dlq")
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0)]}])
    c = _consumer(kafka, FakeProducer(), handler, max_attempts=1)
    await c.run_once()
    assert _value("vypq_events_dead_lettered_total", "infer.ocr.dlq") == before + 1


async def test_failing_dlq_publish_increments_its_own_counter():
    # Đây là chỉ số quan trọng nhất: nó báo partition đang bị kẹt.
    class BrokenProducer(FakeProducer):
        async def publish(self, topic, envelope, key=None):
            raise RuntimeError("broker chết")

    async def handler(_env):
        raise ValueError("dữ liệu hỏng")

    before = _value("vypq_events_dlq_publish_failed_total", "infer.ocr.dlq")
    kafka = FakeConsumer(batches=[{TOPIC_TP: [_msg(0)]}])
    c = _consumer(kafka, BrokenProducer(), handler, max_attempts=1)
    await c.run_once()
    assert _value("vypq_events_dlq_publish_failed_total", "infer.ocr.dlq") == before + 1
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Chạy: `uv run pytest packages/vypq-events/tests/test_consumer.py -v`
Mong đợi: ba test mới FAIL vì counter chưa tồn tại; các test cũ vẫn PASS.

- [ ] **Step 3: Viết vypq_core/metrics.py**

```python
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
```
Thêm `"prometheus-client>=0.21"` vào dependency của `vypq-core`.

- [ ] **Step 4: Gắn counter vào EventConsumer**

Trong `packages/vypq-events/src/vypq_events/consumer.py`:
- Trong `_pause()`: `EVENTS_PAUSED.labels(topic=self._topic).inc()`
- Trong `_to_dlq`, sau khi publish thành công: `EVENTS_DEAD_LETTERED.labels(topic=self._dlq_topic).inc()`
- Trong nhánh `except` của publish DLQ: `DLQ_PUBLISH_FAILED.labels(topic=self._dlq_topic).inc()` trước khi `raise _PauseSignal`

`EventConsumer.__init__` cần nhớ `self._topic = topic` nếu chưa có.

- [ ] **Step 5: Gắn `/metrics` vào gateway và các service**

Thêm `build_metrics_router()` vào danh sách router trong `gateway.main.create_gateway()`,
`ocr_service.main.build_app_with`, `asr_service.main.build_app_with`, và template.

- [ ] **Step 6: Cấu hình Prometheus và alert**

`infra/prometheus/prometheus.yml`:
```yaml
global: {scrape_interval: 15s}
rule_files: [/etc/prometheus/alerts.yml]
scrape_configs:
  - job_name: gateway
    static_configs: [{targets: ["gateway:8080"]}]
  - job_name: services
    static_configs: [{targets: ["ocr:8001", "asr:8002"]}]
  # Redpanda tự phát metric của nó, trong đó có độ trễ (lag) của từng consumer
  # group. Đây là chỉ số cho biết worker có theo kịp hàng đợi không — thứ mà
  # counter của chính ứng dụng không thấy được.
  - job_name: redpanda
    metrics_path: /public_metrics
    static_configs: [{targets: ["redpanda:9644"]}]
```

`infra/prometheus/alerts.yml`:
```yaml
groups:
  - name: vypq
    rules:
      - alert: DlqPublishFailing
        expr: increase(vypq_events_dlq_publish_failed_total[5m]) > 0
        for: 1m
        labels: {severity: critical}
        annotations:
          summary: "Không ghi được vào DLQ trên {{ $labels.topic }}"
          description: >
            Consumer không đẩy được message hỏng vào dead-letter nên nó dừng và
            tua lại mãi. Cả partition đang kẹt sau một message. Không có cảnh báo
            này thì tình trạng đó hoàn toàn im lặng.

      - alert: ConsumerLagGrowing
        # TÊN METRIC PHẢI TỰ XÁC MINH, đừng chép nguyên: nó khác nhau giữa các
        # phiên bản Redpanda. Xem Step 7 để lấy tên thật rồi thay vào đây.
        expr: <TÊN_METRIC_LAG_THẬT> > 1000
        for: 10m
        labels: {severity: warning}
        annotations:
          summary: "Hàng đợi tồn đọng trên {{ $labels.topic }}"
          description: >
            Worker không theo kịp lượng việc đẩy vào. Nếu đi kèm
            ConsumerPausedTooLong thì nguyên nhân là hạ tầng; nếu không thì
            là thiếu worker hoặc model chạy chậm hơn dự kiến.

      - alert: ConsumerPausedTooLong
        expr: increase(vypq_events_consumer_paused_total[15m]) > 3
        for: 5m
        labels: {severity: warning}
        annotations:
          summary: "Consumer dừng liên tục trên {{ $labels.topic }}"
          description: >
            Dừng vài lần là bình thường khi máy GPU thuê được thay. Dừng liên
            tục nghĩa là không có host nào sống, hoặc token đã đổi mà chưa
            đăng ký lại.
```

Thêm service `prometheus` và `grafana` vào compose, mount hai file trên.

- [ ] **Step 7: Chạy test và kiểm alert nạp được**

**Trước hết lấy tên metric lag THẬT** — nó khác nhau giữa các phiên bản Redpanda,
nên đây là chỗ phải xác minh chứ không được chép:
```bash
docker compose -f infra/compose/docker-compose.dev.yml up -d redpanda
curl -s localhost:9644/public_metrics | grep -i 'lag' | head -5
```
Lấy tên đầy đủ xuất hiện ở đó, thay vào `<TÊN_METRIC_LAG_THẬT>` trong
`alerts.yml`. Nếu không có metric lag nào, ghi lại điều đó và dùng
`rpk group describe` trong một exporter nhỏ thay thế — nhưng **đừng để nguyên
placeholder trong file cấu hình**.

```bash
uv run pytest -q
docker compose -f infra/compose/docker-compose.dev.yml up -d prometheus
sleep 5
curl -fsS localhost:9090/api/v1/rules | grep -q DlqPublishFailing
curl -fsS localhost:9090/api/v1/rules | grep -q ConsumerLagGrowing
curl -fsS 'localhost:9090/api/v1/targets' | grep -q '"job":"redpanda"'
```
Mong đợi: test PASS, Prometheus nạp được cả ba rule, và target redpanda ở
trạng thái `up`. Nếu target down thì alert lag là vô nghĩa — sửa cho nó lên.

- [ ] **Step 8: Commit**

```bash
uv run ruff check . --fix
git add packages apps services infra
git commit -m "feat(observability): metric cho pause và DLQ, alert cho partition kẹt"
```

---

## Hoàn tất Plan B1

Sau Task 15, gateway dùng được hoàn toàn bằng `curl`:

```bash
# thuê máy GPU, chạy model-host, lấy URL ngrok rồi:
curl -X POST localhost:8080/v1/hosts -H 'Content-Type: application/json' \
  -d '{"name":"gpu-1","url":"https://xxx.ngrok.app","token":"..."}'

curl localhost:8080/v1/hosts        # xem máy nào đang sống, phục vụ model gì
curl -F service=ocr -F file=@hoadon.jpg localhost:8080/v1/invoke/upload
curl 'localhost:8080/v1/runs?limit=10'
```

Máy hết giờ và tắt → poller thấy, host quá hạn, tự gỡ khỏi định tuyến. Thuê máy
mới → đăng ký lại URL ngrok mới, service tự thấy trong 15s, không restart gì cả.

**Plan B2** dựng dashboard Next.js trên đúng các API này. **Plan C** dùng
`/v1/invoke` async và bảng `runs` để chấm điểm model.
