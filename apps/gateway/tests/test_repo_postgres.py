import os

import pytest
from gateway.db.models import Base
from gateway.db.repo import HostRepo
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
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
