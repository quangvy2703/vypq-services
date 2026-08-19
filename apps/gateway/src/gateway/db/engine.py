from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


def make_engine(url: str) -> AsyncEngine:
    # hide_parameters=True: StatementError.__str__() mặc định in kèm tham số
    # đã bind vào câu lệnh. vypq_core/errors.py log error=str(exc) cho MỌI
    # exception không bắt được — một lần DB trục trặc giữa lúc đăng ký host
    # (bind token vào INSERT/UPDATE) sẽ in thẳng token đó ra log dạng cleartext
    # nếu không có cờ này.
    return create_async_engine(url, pool_pre_ping=True, hide_parameters=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
