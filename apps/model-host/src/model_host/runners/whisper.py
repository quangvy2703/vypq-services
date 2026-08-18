import io

from vypq_contracts.asr import RawAsrOutput, Segment
from vypq_contracts.common import Task

from model_host.spec import ModelSpec


class WhisperRunner:
    task = Task.ASR

    def __init__(self) -> None:
        self._model = None

    def load(self, spec: ModelSpec) -> None:
        try:
            # Import muộn: chỉ máy GPU mới có gói này, module vẫn phải import
            # được ở mọi nơi để registry liệt kê được model.
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "thiếu extra 'gpu': chạy `uv sync --extra gpu` trên máy có CUDA. "
                "Trên máy dev không GPU, dùng runner 'fake-asr' trong models.dev.yaml."
            ) from exc

        self._model = WhisperModel(
            spec.source.get("repo", "large-v3"),
            device=spec.params.get("device", "cuda"),
            compute_type=spec.params.get("compute_type", "float16"),
        )

    def unload(self) -> None:
        self._model = None

    def predict(self, data: bytes, params: dict) -> RawAsrOutput:
        segments, _info = self._model.transcribe(
            io.BytesIO(data),
            language=params.get("language", "vi"),
            vad_filter=params.get("vad_filter", True),
        )
        return RawAsrOutput(
            segments=[
                Segment(start=float(s.start), end=float(s.end), text=s.text.strip())
                for s in segments
            ]
        )
