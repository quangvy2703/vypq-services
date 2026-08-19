import asyncio

import pytest
from gateway.db.models import Base
from gateway.db.repo import RunRepo
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
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


@pytest.fixture
async def factory(tmp_path):
    # In-memory SQLite gives each connection its own private database, so two
    # sessions from an in-memory engine would never actually collide — the
    # race would be fake and the test would pass without proving anything.
    # A file-backed database is shared across connections, which is what it
    # takes to make two concurrent sessions genuinely contend on the same
    # (trace_id, model_version) UNIQUE constraint, like two real HTTP/Kafka
    # consumer workers would.
    db_path = tmp_path / "runs.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
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
    run = await repo.record(
        trace_id="t9", service="ocr", model_version="m1", mode=InvokeMode.ASYNC,
        status=RunStatus.FAILED, input_uri=None, output=None, latency_ms=None,
        error="gpu chết",
    )
    assert run.error == "gpu chết"
    assert run.output is None


async def test_concurrent_record_of_the_same_key_does_not_raise(factory):
    # Kafka giao ít nhất một lần; bản sao là chuyện bình thường, không phải lỗi.
    # Nếu IntegrityError bay ra, consumer sẽ dead-letter một kết quả ĐÃ CHẠY XONG.
    async def once():
        async with factory() as s:
            return await RunRepo(s).record(
                trace_id="dua", service="ocr", model_version="m1",
                mode=InvokeMode.ASYNC, status=RunStatus.OK, input_uri=None,
                output={"ok": True}, latency_ms=1, error=None,
            )

    a, b = await asyncio.gather(once(), once())
    assert a.id == b.id
    async with factory() as s:
        _runs, total = await RunRepo(s).list_runs(trace_id="dua")
    assert total == 1
