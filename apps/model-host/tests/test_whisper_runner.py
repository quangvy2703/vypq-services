import math
import struct
import wave

import pytest
from model_host.runners.whisper import WhisperRunner
from model_host.spec import ModelSpec
from vypq_contracts.asr import RawAsrOutput
from vypq_contracts.common import ModelKind, Task

pytestmark = pytest.mark.slow

SPEC = ModelSpec(
    id="whisper-large-v3", task=Task.ASR, kind=ModelKind.OPENSOURCE, runner="whisper",
    vram_mb=6000, source={"repo": "large-v3"}, params={"language": "vi"},
)


def test_predict_returns_segments_with_increasing_timestamps(tmp_path):
    path = tmp_path / "tone.wav"
    _write_tone(path)
    runner = WhisperRunner()
    runner.load(SPEC)
    try:
        output = runner.predict(path.read_bytes(), SPEC.params)
    finally:
        runner.unload()
    assert isinstance(output, RawAsrOutput)
    for earlier, later in zip(output.segments, output.segments[1:], strict=False):
        assert earlier.end <= later.start


def _write_tone(path, seconds: float = 2.0, rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 220 * t / rate)))
            for t in range(int(rate * seconds))
        )
        handle.writeframes(frames)
