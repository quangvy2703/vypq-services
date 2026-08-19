from pathlib import Path

import httpx
import respx
import structlog.testing
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


def test_gateway_source_without_url_logs_a_warning(tmp_path):
    # Rơi về static lặng lẽ là chính cái nguy hiểm: operator tưởng service
    # đang theo gateway trong khi thực ra chạy danh sách tĩnh cũ, không có
    # cách nào biết trừ khi log nói rõ.
    body = GATEWAY.replace("  url: http://gateway:8080/v1/discovery/hosts\n", "")
    with structlog.testing.capture_logs() as captured:
        build_host_registry(_settings(tmp_path, body))
    events = [entry["event"] for entry in captured]
    assert "host_discovery_gateway_missing_url" in events


def test_missing_config_file_gives_an_empty_static_registry(tmp_path):
    settings = OcrSettings(service_name="ocr", hosts_path=tmp_path / "khong-co.yaml")
    registry = build_host_registry(settings)
    assert isinstance(registry, StaticHostRegistry)


@respx.mock
async def test_gateway_source_token_is_read_from_the_environment_and_sent_as_bearer(
    tmp_path, monkeypatch
):
    # /v1/discovery/hosts giờ đòi auth như mọi route /v1 khác của gateway.
    # `host_discovery.token` trong config.yaml phải là ${TEN_BIEN}, được thay
    # bằng giá trị môi trường lúc đọc (không hardcode bí mật vào file commit
    # git) — và giá trị đó phải đi ra ngoài đúng như header Authorization.
    monkeypatch.setenv("VYPQ_GATEWAY_TOKEN_TEST", "tu-moi-truong")
    body = GATEWAY.replace(
        "  refresh_s: 15\n", "  token: ${VYPQ_GATEWAY_TOKEN_TEST}\n  refresh_s: 15\n"
    )
    route = respx.get(
        "http://gateway:8080/v1/discovery/hosts",
        headers={"authorization": "Bearer tu-moi-truong"},
    ).mock(return_value=httpx.Response(200, json={"hosts": []}))
    registry = build_host_registry(_settings(tmp_path, body))
    await registry.hosts()
    assert route.called
    await registry.aclose()
