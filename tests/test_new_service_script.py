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
    assert (generated / "service.yaml").is_file()

    result = subprocess.run(
        ["uv", "run", "pytest", "services/tmptest", "-q"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


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
