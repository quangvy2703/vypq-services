import httpx
import pytest
import respx
from asr_service.backend.remote import RemoteAsrBackend
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.hosting import ModelInfo
from vypq_core.host_registry import HostRef, StaticHostRegistry
from vypq_core.http_client import UpstreamError

HOST_A = "http://gpu-a:9000"


def _host(name: str, url: str) -> HostRef:
    return HostRef(
        name=name, url=url, token="tk",
        models=[ModelInfo(id="m1", task=Task.ASR, kind=ModelKind.OPENSOURCE, runner="whisper")],
    )


async def _noop_sleep(_s: float) -> None:
    return None


def _backend(hosts: list[HostRef], **kw) -> RemoteAsrBackend:
    return RemoteAsrBackend(
        StaticHostRegistry(hosts), sleep=_noop_sleep, jitter=lambda: 0.0, **kw
    )


@respx.mock
async def test_non_json_body_pauses_instead_of_dead_lettering():
    # Trang xen ngrok trả HTML kèm status 200 khi tunnel chết theo kiểu lạ.
    respx.post(f"{HOST_A}/v1/infer/upload").mock(
        return_value=httpx.Response(200, content=b"<html>ngrok interstitial</html>")
    )
    backend = _backend([_host("a", HOST_A)], max_attempts=1)
    with pytest.raises(UpstreamError):
        await backend.infer(b"x", "m1")


@respx.mock
async def test_contract_mismatch_pauses_instead_of_dead_lettering():
    # model-host phát trường mới, hoặc task lạ, trước khi vypq-contracts được
    # nâng cấp theo — lệch hợp đồng, không phải dữ liệu request hỏng.
    bad_body = {"model_id": "m1", "task": "khong-ton-tai", "timing": {}}
    respx.post(f"{HOST_A}/v1/infer/upload").mock(return_value=httpx.Response(200, json=bad_body))
    backend = _backend([_host("a", HOST_A)], max_attempts=1)
    with pytest.raises(UpstreamError):
        await backend.infer(b"x", "m1")
