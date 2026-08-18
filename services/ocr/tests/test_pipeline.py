import io
import unicodedata

import pytest
from ocr_service.pipeline.postprocess import (
    build_full_text,
    group_lines,
    normalize_text,
    rescale_boxes,
    sort_reading_order,
    text_from_lines,
    to_result,
)
from ocr_service.pipeline.preprocess import prepare_image
from PIL import Image
from vypq_contracts.ocr import RawOcrOutput, TextBox
from vypq_core.errors import ServiceError


def _box(id_: int, x: float, y: float, w: float = 50, h: float = 20, text: str = "x") -> TextBox:
    return TextBox(
        id=id_, polygon=[(x, y), (x + w, y), (x + w, y + h), (x, y + h)], text=text
    )


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_prepare_image_keeps_small_image_unchanged():
    prepared = prepare_image(_png(800, 600), max_side=2000)
    assert prepared.scale == 1.0
    assert (prepared.width, prepared.height) == (800, 600)


def test_prepare_image_shrinks_long_side_to_max():
    prepared = prepare_image(_png(4000, 1000), max_side=2000)
    assert prepared.scale == 0.5
    assert (prepared.width, prepared.height) == (2000, 500)
    assert Image.open(io.BytesIO(prepared.data)).size == (2000, 500)


def test_rescale_boxes_maps_coordinates_back_to_original():
    boxes = [_box(0, 100, 200, w=50, h=20)]
    scaled = rescale_boxes(boxes, 2.0)
    assert scaled[0].polygon[0] == (200.0, 400.0)
    assert scaled[0].polygon[2] == (300.0, 440.0)


def test_rescale_preserves_text_and_confidence():
    box = TextBox(
        id=0, polygon=[(0, 0), (1, 0), (1, 1), (0, 1)], text="ế", confidence=0.5, ignore=True
    )
    out = rescale_boxes([box], 3.0)[0]
    assert (out.text, out.confidence, out.ignore) == ("ế", 0.5, True)


def test_sort_reading_order_groups_boxes_on_the_same_line():
    boxes = [
        _box(0, 300, 10, text="ba"),
        _box(1, 10, 12, text="mot"),
        _box(2, 150, 11, text="hai"),
    ]
    assert [b.text for b in sort_reading_order(boxes)] == ["mot", "hai", "ba"]


def test_sort_reading_order_orders_lines_top_to_bottom():
    boxes = [
        _box(0, 10, 100, text="duoi"),
        _box(1, 10, 10, text="tren"),
    ]
    assert [b.text for b in sort_reading_order(boxes)] == ["tren", "duoi"]


def test_sort_reading_order_tolerates_slight_vertical_jitter():
    # Cùng dòng nhưng lệch vài pixel — không được tách thành hai dòng.
    boxes = [
        _box(0, 200, 14, text="sau"),
        _box(1, 10, 10, text="truoc"),
    ]
    assert [b.text for b in sort_reading_order(boxes)] == ["truoc", "sau"]


def test_build_full_text_joins_lines_with_newline_and_words_with_space():
    boxes = [
        _box(0, 10, 10, text="CONG TY"),
        _box(1, 200, 11, text="ABC"),
        _box(2, 10, 100, text="HOA DON"),
    ]
    assert build_full_text(sort_reading_order(boxes)) == "CONG TY ABC\nHOA DON"


def test_build_full_text_skips_ignored_boxes():
    boxes = [_box(0, 10, 10, text="giu"), _box(1, 200, 10, text="bo")]
    boxes[1].ignore = True
    assert build_full_text(sort_reading_order(boxes)) == "giu"


def test_normalize_text_converts_decomposed_vietnamese_to_nfc():
    decomposed = unicodedata.normalize("NFD", "Hóa đơn tiếng Việt")
    assert decomposed != "Hóa đơn tiếng Việt"
    assert normalize_text(decomposed) == "Hóa đơn tiếng Việt"
    assert unicodedata.is_normalized("NFC", normalize_text(decomposed))


def test_to_result_rescales_sorts_and_normalizes_in_one_pass():
    raw = RawOcrOutput(
        boxes=[
            _box(0, 100, 5, text=unicodedata.normalize("NFD", "đơn")),
            _box(1, 10, 6, text=unicodedata.normalize("NFD", "hóa")),
        ]
    )
    result = to_result(raw, scale=0.5)
    assert result.full_text == "hóa đơn"
    assert unicodedata.is_normalized("NFC", result.full_text)
    assert result.boxes[0].polygon[0] == (20.0, 12.0)   # 10 / 0.5


def test_full_text_never_disagrees_with_box_order_on_jittered_text():
    # Chữ hơi nghiêng: box trên cùng và box trái nhất của một dòng là hai box khác
    # nhau. Trước khi gom dòng về một nguồn, hai hàm ngắt dòng khác nhau ở đây.
    boxes = [_box(0, 200, 0, text="B"), _box(1, 400, 8, text="C"),
             _box(2, 10, 11, text="A"), _box(3, 250, 14, text="D")]
    lines = group_lines(boxes)
    ordered = sort_reading_order(boxes)

    assert ordered == [b for line in lines for b in line]
    assert build_full_text(ordered) == text_from_lines(lines)
    # Số dòng trong full_text bằng số dòng CÓ CHỮ (dòng toàn box ignore bị bỏ).
    visible = [line for line in lines if any(not b.ignore for b in line)]
    assert build_full_text(ordered).count("\n") + 1 == len(visible)


def test_a_large_ignored_stamp_does_not_merge_real_lines():
    # Con dấu mờ cao 200px cạnh chữ cao 20px: nếu tolerance tính cả nó thì hai
    # dòng chữ cách nhau 60px bị gộp làm một.
    boxes = [_box(0, 10, 0, text="LineA"), _box(1, 10, 60, text="LineB")]
    for idx, y in ((2, 0), (3, 300)):
        stamp = _box(idx, 400, y, w=200, h=200, text="")
        stamp.ignore = True
        boxes.append(stamp)
    assert build_full_text(sort_reading_order(boxes)) == "LineA\nLineB"


def test_a_fully_ignored_line_is_dropped_without_leaving_a_blank():
    boxes = [_box(0, 10, 0, text="Tren"), _box(1, 10, 60, text=""),
             _box(2, 10, 120, text="Duoi")]
    boxes[1].ignore = True
    assert build_full_text(sort_reading_order(boxes)) == "Tren\nDuoi"


def test_two_column_layout_interleaves_columns_known_limitation():
    # Hạn chế đã biết, cố ý ghim lại để nó là quyết định chứ không phải bất ngờ:
    # gom theo dải ngang nên hai cột bị trộn. Tách cột thuộc phạm vi sau.
    boxes = []
    for row in range(3):
        boxes.append(_box(row * 2, 10, row * 60, text=f"T{row}"))
        boxes.append(_box(row * 2 + 1, 500, row * 60, text=f"P{row}"))
    assert build_full_text(sort_reading_order(boxes)) == "T0 P0\nT1 P1\nT2 P2"


def test_prepare_image_rejects_an_oversized_image():
    # Ảnh nhỏ + ngưỡng thấp: kiểm đúng hành vi mà không dựng ảnh 144 triệu điểm
    # ảnh thật (tốn RAM trong CI và làm Pillow phun DecompressionBombWarning).
    buf = io.BytesIO()
    Image.new("RGB", (2000, 2000), "white").save(buf, format="PNG")
    with pytest.raises(ServiceError) as exc:
        prepare_image(buf.getvalue(), max_side=2000, max_pixels=1_000)
    assert exc.value.http_status == 422
    assert "điểm ảnh" in exc.value.message


def test_to_result_on_empty_output_gives_empty_text():
    result = to_result(RawOcrOutput(boxes=[]), scale=1.0)
    assert result.full_text == ""
    assert result.boxes == []
