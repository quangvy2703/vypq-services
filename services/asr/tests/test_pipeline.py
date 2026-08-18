import unicodedata

from asr_service.pipeline.postprocess import build_transcript, merge_segments, to_result
from vypq_contracts.asr import RawAsrOutput, Segment


def _seg(start: float, end: float, text: str, speaker: str | None = None) -> Segment:
    return Segment(start=start, end=end, text=text, speaker=speaker)


def test_merge_joins_segments_separated_by_a_short_gap():
    merged = merge_segments([_seg(0.0, 1.0, "xin"), _seg(1.1, 2.0, "chào")], gap_s=0.3)
    assert len(merged) == 1
    assert merged[0].text == "xin chào"
    assert (merged[0].start, merged[0].end) == (0.0, 2.0)


def test_merge_keeps_segments_separated_by_a_long_gap():
    merged = merge_segments([_seg(0.0, 1.0, "xin"), _seg(5.0, 6.0, "chào")], gap_s=0.3)
    assert len(merged) == 2


def test_merge_never_joins_across_different_speakers():
    merged = merge_segments(
        [_seg(0.0, 1.0, "xin", "A"), _seg(1.1, 2.0, "chào", "B")], gap_s=0.3
    )
    assert len(merged) == 2


def test_merge_on_empty_input_returns_empty():
    assert merge_segments([]) == []


def test_build_transcript_joins_with_single_space_and_normalizes_nfc():
    decomposed = unicodedata.normalize("NFD", "tiếng Việt")
    transcript = build_transcript([_seg(0.0, 1.0, "xin chào"), _seg(1.2, 2.0, decomposed)])
    assert transcript == "xin chào tiếng Việt"
    assert unicodedata.is_normalized("NFC", transcript)


def test_to_result_merges_then_builds_text():
    raw = RawAsrOutput(segments=[_seg(0.0, 1.0, "xin"), _seg(1.1, 2.0, "chào")])
    result = to_result(raw)
    assert result.text == "xin chào"
    assert len(result.segments) == 1
