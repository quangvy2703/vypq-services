import subprocess

import pytest

pytestmark = pytest.mark.slow


def test_both_registries_conform_to_the_protocol_by_type():
    # isinstance chỉ thấy method có mặt, không thấy chữ ký. Đây là chỗ duy nhất
    # bắt được một bản cài lease() thành hàm sync.
    source = """
from vypq_core.host_registry import (
    DiscoveryHostRegistry, HostRegistry, StaticHostRegistry,
)


def use(registry: HostRegistry) -> None: ...


use(StaticHostRegistry([]))
use(DiscoveryHostRegistry("http://x"))
"""
    result = subprocess.run(
        ["uv", "run", "mypy", "--command", source], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
