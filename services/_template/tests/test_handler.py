import pytest
from __PKG__.backend.fake import Fake__BACKEND__
from __PKG__.handler import __HANDLER__
from vypq_contracts.__TASK__ import __RAWOUT__


async def test_run_calls_backend_with_default_model():
    # to_result() chưa được cài (NotImplementedError cố ý — xem handler.py),
    # nên chỉ kiểm được phần chọn model_version trước khi tới bước đó.
    backend = Fake__BACKEND__(__RAWOUT__())
    handler = __HANDLER__(backend, default_model="m1")
    with pytest.raises(NotImplementedError):
        await handler.run(b"payload", model_version=None, trace_id="t1")
    assert backend.calls[0][1] == "m1"


async def test_run_uses_requested_model_version():
    backend = Fake__BACKEND__(__RAWOUT__())
    handler = __HANDLER__(backend, default_model="m1")
    with pytest.raises(NotImplementedError):
        await handler.run(b"payload", model_version="m2", trace_id="t1")
    assert backend.calls[0][1] == "m2"


async def test_backend_error_propagates_unchanged():
    handler = __HANDLER__(Fake__BACKEND__(error=RuntimeError("hỏng")), default_model="m1")
    with pytest.raises(RuntimeError):
        await handler.run(b"payload", model_version=None, trace_id="t1")
