import unicodedata

from vypq_contracts.asr import AsrResult, RawAsrOutput, Segment


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def merge_segments(segments: list[Segment], gap_s: float = 0.3) -> list[Segment]:
    """Gộp các đoạn liền nhau của cùng một người nói, cách nhau dưới `gap_s` giây.

    Sắp theo `start` trước khi gộp: nếu đoạn tới không đúng thứ tự thời gian —
    diarization nhiều luồng, hoặc kết quả gộp từ nhiều kênh — thì hiệu
    `segment.start - previous.end` ra số âm và vẫn lọt qua ngưỡng, sinh ra đoạn
    có `end < start` và chữ đảo ngược. Không lỗi, không cảnh báo.
    """
    merged: list[Segment] = []
    for segment in sorted(segments, key=lambda s: s.start):
        previous = merged[-1] if merged else None
        joinable = (
            previous is not None
            and previous.speaker == segment.speaker
            and 0 <= segment.start - previous.end <= gap_s
        )
        if joinable:
            merged[-1] = previous.model_copy(
                update={"end": segment.end, "text": f"{previous.text} {segment.text}".strip()}
            )
        else:
            merged.append(segment)
    return merged


def build_transcript(segments: list[Segment]) -> str:
    return normalize_text(" ".join(s.text for s in segments if s.text).strip())


def to_result(raw: RawAsrOutput) -> AsrResult:
    segments = [
        s.model_copy(update={"text": normalize_text(s.text)})
        for s in merge_segments(raw.segments)
    ]
    return AsrResult(text=build_transcript(segments), segments=segments)
