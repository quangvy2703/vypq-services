from datetime import UTC, datetime

import pytest
from gateway.db.models import Base
from gateway.db.repo import HostRepo
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
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
