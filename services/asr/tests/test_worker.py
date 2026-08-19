import pytest
from asr_service.worker import fetch_bytes
from vypq_core.errors import ServiceError
from vypq_core.http_client import UpstreamError


async def test_unsupported_uri_scheme_is_permanent_not_retryable():
    # UnsupportedProtocol kế thừa TransportError. Xếp nhầm nó vào hạ tầng thì
    # một URI s3:// kẹt cả partition vĩnh viễn và DLQ vẫn rỗng.
    with pytest.raises(ServiceError) as exc:
        await fetch_bytes("s3://bucket/a.jpg")
    assert not isinstance(exc.value, UpstreamError)


async def test_malformed_uri_is_permanent_not_retryable():
    with pytest.raises(ServiceError) as exc:
        await fetch_bytes("khongphaiuri")
    assert not isinstance(exc.value, UpstreamError)
