import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "new-service.sh"


@pytest.fixture
def generated():
    target = REPO / "services" / "tmptest"
    root_pyproject = REPO / "pyproject.toml"
    original = root_pyproject.read_text(encoding="utf-8")
    if target.exists():
        shutil.rmtree(target)
    yield target
    if target.exists():
        shutil.rmtree(target)
    # Script sửa root pyproject — trả lại nguyên trạng để không rác workspace.
    root_pyproject.write_text(original, encoding="utf-8")
    # pyproject.toml phục hồi rồi nhưng uv.lock vẫn còn nhớ tmptest-service trỏ
    # vào thư mục vừa xoá — "uv sync --frozen" (đúng lệnh Dockerfile dùng) sẽ vỡ
    # ngay sau khi chạy xong test này nếu không đồng bộ lại lock ở đây.
    subprocess.run(["uv", "sync"], cwd=REPO, check=True, capture_output=True)


def test_script_generates_a_service_that_passes_its_own_tests(generated):
    subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, check=True, capture_output=True
    )
    assert (generated / "src" / "tmptest_service" / "handler.py").is_file()
    assert (generated / "src" / "tmptest_service" / "worker.py").is_file()
    # service.yaml đã bị xoá: /v1/info là nguồn sự thật sống thay nó. Kiểm tĩnh
    # trên source sinh ra, không khởi động server ở đây — test riêng bên dưới
    # (test_script_generated_service_advertises_itself_via_v1_info) đã lo phần
    # gọi HTTP thật; test này chỉ cần chắc invoke_path khai trong ServiceInfo
    # khớp đúng route POST mà chính main.py vừa sinh đăng ký.
    main_py = (generated / "src" / "tmptest_service" / "main.py").read_text(encoding="utf-8")
    assert "ServiceInfo(" in main_py
    invoke_path_match = re.search(r'invoke_path=["\'](/v1/[^"\']+)["\']', main_py)
    assert invoke_path_match, f"không tìm thấy invoke_path trong {main_py!r}"
    route_match = re.search(r'@router\.post\(\s*["\'](/[^"\']+)["\']', main_py)
    assert route_match, f"không tìm thấy route POST trong {main_py!r}"
    assert invoke_path_match.group(1) == "/v1" + route_match.group(1)

    result = subprocess.run(
        ["uv", "run", "pytest", "services/tmptest", "-q"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_script_generated_service_advertises_itself_via_v1_info(generated):
    subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, check=True, capture_output=True
    )
    # Không import trực tiếp trong tiến trình test: gói vừa sinh chỉ nằm trong
    # venv sau "uv sync" mà script đã tự chạy — python con của "uv run" mới
    # chắc chắn thấy nó trên sys.path.
    probe = (
        "import json\n"
        "import httpx\n"
        "from tmptest_service.main import build_app\n"
        "app = build_app()\n"
        "transport = httpx.ASGITransport(app=app)\n"
        "async def _get():\n"
        "    async with httpx.AsyncClient(transport=transport, base_url='http://t') as c:\n"
        "        return await c.get('/v1/info')\n"
        "import asyncio\n"
        "resp = asyncio.run(_get())\n"
        "print(json.dumps(resp.json()))\n"
    )
    result = subprocess.run(
        ["uv", "run", "python", "-c", probe],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    generated_info = json.loads(result.stdout.strip().splitlines()[-1])
    assert "/v1/" in generated_info["invoke_path"]
    # Route thật đăng ký trong main.py là "/v1/" + task (ocr ở đây), không phải
    # slug — sai chỗ này thì gateway gọi invoke_path sẽ 404 dù /v1/info vẫn ok.
    assert generated_info["invoke_path"] == "/v1/ocr"


def test_script_leaves_no_unreplaced_tokens(generated):
    subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, check=True, capture_output=True
    )
    for path in generated.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in (
                "__SLUG__", "__PKG__", "__TASK__", "__TASKUPPER__",
                "__RAWOUT__", "__RESP__", "__BACKEND__", "__HANDLER__", "__PORT__",
            ):
                assert token not in text, f"{path} còn sót {token}"


def test_script_registers_the_new_service_in_the_workspace_root(generated):
    subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, check=True, capture_output=True
    )
    root = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert '"tmptest-service",' in root
    assert "tmptest-service = { workspace = true }" in root
    # Đăng ký rồi thì venv phải import được gói mới.
    result = subprocess.run(
        ["uv", "run", "python", "-c", "import tmptest_service"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_script_refuses_to_overwrite_existing_service(generated):
    subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, check=True, capture_output=True
    )
    result = subprocess.run(
        [str(SCRIPT), "tmptest", "ocr", "8099"], cwd=REPO, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "đã tồn tại" in result.stderr
