import pytest
from model_host.runners.paddle import PaddleOcrRunner
from model_host.spec import ModelSpec
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.ocr import RawOcrOutput

pytestmark = pytest.mark.slow

SPEC = ModelSpec(
    id="paddleocr-v4-vi", task=Task.OCR, kind=ModelKind.OPENSOURCE,
    runner="paddle", vram_mb=2500, params={"lang": "vi", "use_angle_cls": True},
)


@pytest.fixture(scope="module")
def runner() -> PaddleOcrRunner:
    r = PaddleOcrRunner()
    r.load(SPEC)
    yield r
    r.unload()


def test_predict_returns_raw_ocr_output(runner, tmp_path_factory):
    image_path = tmp_path_factory.mktemp("img") / "sample.png"
    _write_sample_image(image_path, "HOA DON")
    output = runner.predict(image_path.read_bytes(), SPEC.params)
    assert isinstance(output, RawOcrOutput)
    assert len(output.boxes) >= 1
    assert all(len(b.polygon) >= 4 for b in output.boxes)
    assert "HOA DON" in " ".join(b.text for b in output.boxes).upper()


def _write_sample_image(path, text: str) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(image).text((20, 40), text, fill="black")
    image.save(path)
