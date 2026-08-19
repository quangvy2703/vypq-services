from pathlib import Path

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


def test_missing_config_file_gives_an_empty_static_registry(tmp_path):
    settings = OcrSettings(service_name="ocr", hosts_path=tmp_path / "khong-co.yaml")
    registry = build_host_registry(settings)
    assert isinstance(registry, StaticHostRegistry)
