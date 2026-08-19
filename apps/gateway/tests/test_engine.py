import pytest
from gateway.db.engine import make_engine
from sqlalchemy import text
from sqlalchemy.exc import StatementError

TOKEN = "sekret-host-token-do-khong-duoc-lo-ra"


async def test_failing_statement_does_not_leak_bound_parameters():
    # Bug gốc: create_async_engine() không truyền hide_parameters=True, nên
    # StatementError.__str__() (thứ mà vypq_core/errors.py log qua str(exc)
    # cho mọi exception không bắt được) in kèm nguyên văn tham số đã bind.
    # Một câu lệnh hỏng trong lúc đăng ký host (token nằm trong tham số bind)
    # sẽ in token ra log dạng cleartext.
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            with pytest.raises(StatementError) as excinfo:
                await conn.execute(
                    text("SELECT * FROM bang_khong_ton_tai WHERE token = :token"),
                    {"token": TOKEN},
                )
        assert TOKEN not in str(excinfo.value)
    finally:
        await engine.dispose()
