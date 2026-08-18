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


def group_lines(boxes: list[TextBox]) -> list[list[TextBox]]:
    """Gom box thành dòng theo tâm y, mỗi dòng sắp trái sang phải.

    NGUỒN DUY NHẤT quyết định đâu là một dòng. Trước đây `sort_reading_order` và
    `build_full_text` mỗi hàm tự gom một kiểu: hàm đầu neo vào box TRÊN CÙNG của
    dòng, hàm sau neo vào box TRÁI NHẤT. Với chữ hơi nghiêng — đúng thứ xảy ra khi
    chụp hoá đơn bằng điện thoại — hai mốc đó khác nhau, nên `full_text` ngắt dòng
    một đằng còn thứ tự `boxes` một nẻo. Kết quả đọc vẫn xuôi tai nhưng chấm CER
    thì sai, và model bị đổ oan.

    Hạn chế đã biết: thuật toán này gom theo dải ngang, nên tài liệu HAI CỘT sẽ bị
    trộn xen kẽ trái–phải từng dòng. Với hoá đơn một cột thì đúng; bố cục hai cột
    cần tách cột trước (XY-cut) — chưa làm ở Plan A, xem test đánh dấu bên dưới.
    """
    if not boxes:
        return []
    tolerance = statistics.median(_height(b) for b in boxes) * _LINE_TOLERANCE_RATIO
    lines: list[list[TextBox]] = []
    for box in sorted(boxes, key=_y_center):
        if lines and abs(_y_center(box) - _y_center(lines[-1][0])) <= tolerance:
            lines[-1].append(box)
        else:
            lines.append([box])
    return [sorted(line, key=_min_x) for line in lines]


def sort_reading_order(boxes: list[TextBox]) -> list[TextBox]:
    return [box for line in group_lines(boxes) for box in line]


def text_from_lines(lines: list[list[TextBox]]) -> str:
    """Ghép theo dòng: cùng dòng nối bằng dấu cách, khác dòng xuống hàng."""
    rendered = [
        " ".join(box.text for box in line if not box.ignore) for line in lines
    ]
    return normalize_text("\n".join(line for line in rendered if line))


def build_full_text(boxes: list[TextBox]) -> str:
    return text_from_lines(group_lines(boxes))


def to_result(raw: RawOcrOutput, scale: float) -> OcrResult:
    factor = 1.0 / scale if scale else 1.0
    boxes = rescale_boxes(raw.boxes, factor)
    boxes = [b.model_copy(update={"text": normalize_text(b.text)}) for b in boxes]
    # Gom dòng đúng MỘT lần rồi dùng chung cho cả hai đầu ra: thứ tự box và
    # full_text không thể lệch nhau nữa vì chúng sinh ra từ cùng một kết quả.
    lines = group_lines(boxes)
    return OcrResult(
        full_text=text_from_lines(lines),
        boxes=[box for line in lines for box in line],
    )
