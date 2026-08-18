import statistics
import unicodedata

from vypq_contracts.ocr import OcrResult, RawOcrOutput, TextBox

_LINE_TOLERANCE_RATIO = 0.6


def normalize_text(text: str) -> str:
    """Tiếng Việt phải về NFC, nếu không CER so với ground truth sẽ sai."""
    return unicodedata.normalize("NFC", text)


def rescale_boxes(boxes: list[TextBox], factor: float) -> list[TextBox]:
    if factor == 1.0:
        return list(boxes)
    return [
        box.model_copy(update={"polygon": [(x * factor, y * factor) for x, y in box.polygon]})
        for box in boxes
    ]


def _y_center(box: TextBox) -> float:
    return sum(y for _x, y in box.polygon) / len(box.polygon)


def _min_x(box: TextBox) -> float:
    return min(x for x, _y in box.polygon)


def _height(box: TextBox) -> float:
    ys = [y for _x, y in box.polygon]
    return max(ys) - min(ys)


def sort_reading_order(boxes: list[TextBox]) -> list[TextBox]:
    """Gom box thành dòng theo tâm y, rồi sắp trái sang phải trong mỗi dòng."""
    if not boxes:
        return []
    tolerance = statistics.median(_height(b) for b in boxes) * _LINE_TOLERANCE_RATIO
    lines: list[list[TextBox]] = []
    for box in sorted(boxes, key=_y_center):
        if lines and abs(_y_center(box) - _y_center(lines[-1][0])) <= tolerance:
            lines[-1].append(box)
        else:
            lines.append([box])
    ordered: list[TextBox] = []
    for line in lines:
        ordered.extend(sorted(line, key=_min_x))
    return ordered


def build_full_text(boxes: list[TextBox]) -> str:
    """Ghép theo dòng: cùng dòng nối bằng dấu cách, khác dòng xuống hàng."""
    kept = [b for b in boxes if not b.ignore]
    if not kept:
        return ""
    tolerance = statistics.median(_height(b) for b in kept) * _LINE_TOLERANCE_RATIO
    lines: list[list[str]] = []
    previous: TextBox | None = None
    for box in kept:
        if previous is not None and abs(_y_center(box) - _y_center(previous)) <= tolerance:
            lines[-1].append(box.text)
        else:
            lines.append([box.text])
            previous = box
    return normalize_text("\n".join(" ".join(line) for line in lines))


def to_result(raw: RawOcrOutput, scale: float) -> OcrResult:
    factor = 1.0 / scale if scale else 1.0
    boxes = rescale_boxes(raw.boxes, factor)
    boxes = [b.model_copy(update={"text": normalize_text(b.text)}) for b in boxes]
    boxes = sort_reading_order(boxes)
    return OcrResult(full_text=build_full_text(boxes), boxes=boxes)
