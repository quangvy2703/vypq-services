from datetime import UTC, datetime, timedelta, timezone

import pytest
from gateway.db.models import Base, Host
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


async def test_non_utc_aware_datetime_round_trips_to_the_same_instant(session):
    # +07:00 khác UTC 7 tiếng: nếu cột chỉ gắn nhãn UTC vào con số naive đọc lên
    # từ SQLite (lỗi cũ), giờ đọc lại sẽ lệch 7 tiếng dù instant thực là như nhau.
    repo = HostRepo(session)
    await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000"))
    row = await session.get(Host, "gpu-1")
    plus7 = timezone(timedelta(hours=7))
    written = datetime(2026, 1, 1, 10, 0, tzinfo=plus7)  # = 2026-01-01 03:00 UTC
    row.last_seen_at = written
    await session.commit()
    session.expire_all()  # buộc SELECT lại thật, không dùng object đã có sẵn tzinfo

    state = await repo.get("gpu-1")
    assert state.last_seen_at.tzinfo is not None
    assert state.last_seen_at == written  # so sánh instant, không so số giờ hiển thị
    assert state.last_seen_at.astimezone(UTC) == datetime(2026, 1, 1, 3, 0, tzinfo=UTC)


async def test_naive_datetime_is_rejected_instead_of_guessed(session):
    # "10:00" không có múi giờ là mơ hồ; cột phải từ chối thay vì đoán hộ.
    repo = HostRepo(session)
    await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000"))
    row = await session.get(Host, "gpu-1")
    row.last_seen_at = datetime(2026, 1, 1, 10, 0)  # naive
    with pytest.raises(Exception, match="tzinfo"):
        await session.commit()


async def test_registered_at_comes_back_aware(session):
    # registered_at có cùng kiểu cột và cùng nguy cơ như last_seen_at, nhưng
    # bản vá cũ ở call-site chỉ chạm last_seen_at — cột này từng bị bỏ sót.
    repo = HostRepo(session)
    await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000"))
    session.expire_all()

    row = await session.get(Host, "gpu-1")
    assert row.registered_at.tzinfo is not None


async def test_reregistering_same_url_with_new_token_keeps_health_and_models(session):
    # Cùng URL nghĩa là cùng máy — chỉ đổi credential, không phải đổi máy. healthy
    # và danh sách model đã biết phải giữ nguyên, khác với trường hợp đổi URL.
    repo = HostRepo(session)
    await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000", token="cu"))
    await repo.mark_polled("gpu-1", healthy=True, models=[_model("a"), _model("b")], error=None)

    await repo.upsert(HostRegistration(name="gpu-1", url="http://h:9000", token="moi"))

    state = await repo.get("gpu-1")
    assert state.healthy is True
    assert [m.id for m in state.models] == ["a", "b"]
    assert await repo.token_for("gpu-1") == "moi"
