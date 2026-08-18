import io

from vypq_contracts.common import Task
from vypq_contracts.ocr import RawOcrOutput, TextBox

from model_host.spec import ModelSpec


class PaddleOcrRunner:
    task = Task.OCR

    def __init__(self) -> None:
        self._engine = None

    def load(self, spec: ModelSpec) -> None:
        try:
            # Import muộn: chỉ máy GPU mới có gói này, module vẫn phải import
            # được ở mọi nơi để registry liệt kê được model.
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "thiếu extra 'gpu': chạy `uv sync --extra gpu` trên máy có CUDA. "
                "Trên máy dev không GPU, dùng runner 'fake' trong models.dev.yaml."
            ) from exc

        self._engine = PaddleOCR(
            lang=spec.params.get("lang", "vi"),
            use_angle_cls=spec.params.get("use_angle_cls", True),
            show_log=False,
        )

    def unload(self) -> None:
        self._engine = None

    def predict(self, data: bytes, params: dict) -> RawOcrOutput:
        import numpy as np
        from PIL import Image

        image = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
        raw = self._engine.ocr(image, cls=params.get("use_angle_cls", True))
        lines = raw[0] if raw and raw[0] else []
        boxes = [
            TextBox(
                id=index,
                polygon=[(float(x), float(y)) for x, y in polygon],
                text=text,
                confidence=float(confidence),
            )
            for index, (polygon, (text, confidence)) in enumerate(lines)
        ]
        return RawOcrOutput(boxes=boxes)
