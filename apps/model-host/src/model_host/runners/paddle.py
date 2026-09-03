import io

from vypq_contracts.common import Task
from vypq_contracts.ocr import RawOcrOutput, TextBox
from vypq_core.logging import get_logger

from model_host.spec import ModelSpec

log = get_logger(__name__)

# Những khoá trong `source` mà PaddleOCR 3.x thật sự nạp được: tên model chính
# thức (tự tải về ~/.paddlex) hoặc đường dẫn thư mục model trên đĩa.
#
# Bộ tên này KHÁC hẳn bản 2.x — `rec_model_dir`, `cls_model_dir`,
# `rec_char_dict_path`, `use_angle_cls`, `show_log` đều đã bị gỡ khỏi
# constructor. Giữ lại tên cũ ở đây là mời đúng kiểu hỏng im lặng mà danh sách
# này sinh ra để chặn: yaml khai một đằng, host nạp một nẻo, không ai biết.
_KHOA_SOURCE = (
    "ocr_version",
    "text_detection_model_name",
    "text_detection_model_dir",
    "text_recognition_model_name",
    "text_recognition_model_dir",
    "textline_orientation_model_name",
    "textline_orientation_model_dir",
)

# Ba bước tiền xử lý của pipeline 3.x. Mặc định của paddle là BẬT, và mỗi bước
# là một model nữa phải tải về rồi chạy. Ta chỉ cần dò chữ + đọc chữ, nên tắt cả
# ba trừ khi models.yaml nói khác.
_TIEN_XU_LY = (
    "use_doc_orientation_classify",
    "use_doc_unwarping",
    "use_textline_orientation",
)

# Tham số đổi được theo từng request, không phải theo từng model.
_THAM_SO_PREDICT = ("use_textline_orientation", "text_rec_score_thresh")


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

        nap_duoc = {k: v for k, v in spec.source.items() if k in _KHOA_SOURCE}
        bo_qua = sorted(set(spec.source) - set(nap_duoc))
        if bo_qua:
            # Bỏ qua trong im lặng chính là lỗi cũ: models.yaml khai
            # `{type: hf, repo: PaddlePaddle/PP-OCRv4}`, host phục vụ PP-OCRv3
            # latin, và không chỗ nào nói ra sự chênh lệch đó.
            log.warning(
                "paddle_source_bi_bo_qua",
                model_id=spec.id,
                bo_qua=bo_qua,
                nap_duoc=sorted(nap_duoc),
                ghi_chu="paddle chỉ nạp tên model chính thức hoặc thư mục model "
                "trên đĩa; khai repo HF ở đây không có tác dụng",
            )

        tuy_chon = {k: spec.params.get(k, False) for k in _TIEN_XU_LY}

        # `lang` chỉ gửi xuống khi models.yaml khai hẳn, KHÔNG mặc định "vi".
        # Paddle 3.x ghép (lang, ocr_version) thành một cặp và ném ngay nếu cặp
        # đó không có model: `lang="vi"` + PP-OCRv4 là ValueError, chứ không âm
        # thầm rơi về latin như bản 2.x. Với PP-OCRv6 thì rec model là một bản
        # đa ngữ duy nhất — đặt lang="vi" hay bỏ trống cho ra đúng một kết quả.
        lang = spec.params.get("lang")
        if lang:
            tuy_chon["lang"] = lang

        self._engine = PaddleOCR(**tuy_chon, **nap_duoc)

    def unload(self) -> None:
        self._engine = None

    def predict(self, data: bytes, params: dict) -> RawOcrOutput:
        import numpy as np
        from PIL import Image

        image = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
        rieng = {k: params[k] for k in _THAM_SO_PREDICT if k in params}
        ket_qua = self._engine.predict(image, **rieng)
        if not ket_qua:
            return RawOcrOutput(boxes=[])
        trang = ket_qua[0]

        # `rec_polys` chứ KHÔNG phải `dt_polys`: `rec_texts`/`rec_scores` đã bị
        # lọc theo text_rec_score_thresh, còn `dt_polys` thì chưa. Ghép chữ đã
        # lọc với ô chưa lọc là gán chữ vào sai ô ngay khi có một ô bị loại —
        # sai lệch hình học mà nhìn kết quả không thấy được.
        polygons = trang["rec_polys"]
        texts = trang["rec_texts"]
        scores = trang["rec_scores"]
        if not len(polygons) == len(texts) == len(scores):
            raise RuntimeError(
                "paddle trả số polygon/text/score lệch nhau "
                f"({len(polygons)}/{len(texts)}/{len(scores)}) — ghép lại sẽ gán "
                "chữ vào sai ô, thà hỏng to còn hơn sai lặng lẽ"
            )

        boxes = [
            TextBox(
                id=index,
                polygon=[(float(x), float(y)) for x, y in np.asarray(polygon).tolist()],
                text=text,
                confidence=float(score),
            )
            for index, (polygon, text, score) in enumerate(
                zip(polygons, texts, scores, strict=True)
            )
        ]
        return RawOcrOutput(boxes=boxes)
