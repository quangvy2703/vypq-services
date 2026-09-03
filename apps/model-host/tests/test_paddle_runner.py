import pytest
from model_host.runners.paddle import PaddleOcrRunner
from model_host.spec import ModelSpec
from vypq_contracts.common import ModelKind, Task
from vypq_contracts.ocr import RawOcrOutput

SPEC = ModelSpec(
    id="ppocr-v6", task=Task.OCR, kind=ModelKind.OPENSOURCE,
    runner="paddle", vram_mb=2500, source={"ocr_version": "PP-OCRv6"}, params={},
)


@pytest.fixture(scope="module")
def runner() -> PaddleOcrRunner:
    r = PaddleOcrRunner()
    r.load(SPEC)
    yield r
    r.unload()


@pytest.mark.slow
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


# --- load() phải tôn trọng spec.source ------------------------------------
#
# Trước đây load() chỉ đọc params.lang. models.yaml khai
# `source: {type: hf, repo: PaddlePaddle/PP-OCRv4}` nhưng paddleocr xếp "vi" vào
# nhóm latin, nên host nạp PP-OCRv3 latin — mà latin_dict.txt thiếu ế ộ ổ ủ ă ơ ư.
# Kết quả: "Tổng cộng" ra "Tng c0ng", còn yaml thì vẫn nói v4. Sai trong im lặng.
#
# Tên khoá dưới đây là của paddleocr 3.x (text_recognition_model_dir, ...).
# Bản 2.x dùng rec_model_dir/cls_model_dir/rec_char_dict_path — đã bị gỡ khỏi
# constructor, nên khai tên cũ bây giờ phải rơi vào nhánh "bị bỏ qua".


class _PaddleOcrGia:
    """Ghi lại kwargs mà runner truyền xuống PaddleOCR."""

    da_nhan: dict = {}

    def __init__(self, **kwargs):
        type(self).da_nhan = kwargs


def _cai_paddleocr_gia(monkeypatch) -> type[_PaddleOcrGia]:
    import sys
    import types

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = _PaddleOcrGia
    monkeypatch.setitem(sys.modules, "paddleocr", module)
    return _PaddleOcrGia


def _spec_voi_source(source: dict, params: dict | None = None) -> ModelSpec:
    return ModelSpec(
        id="ppocr-v6", task=Task.OCR, kind=ModelKind.OPENSOURCE,
        runner="paddle", vram_mb=2500, source=source,
        params={"lang": "vi"} if params is None else params,
    )


def test_load_truyen_duong_dan_model_tu_source_xuong_paddle(monkeypatch):
    gia = _cai_paddleocr_gia(monkeypatch)
    spec = _spec_voi_source({
        "text_recognition_model_dir": "/w/vi_rec_infer",
        "text_recognition_model_name": "PP-OCRv6_medium_rec",
        "ocr_version": "PP-OCRv6",
    })

    PaddleOcrRunner().load(spec)

    assert gia.da_nhan["text_recognition_model_dir"] == "/w/vi_rec_infer"
    assert gia.da_nhan["text_recognition_model_name"] == "PP-OCRv6_medium_rec"
    assert gia.da_nhan["ocr_version"] == "PP-OCRv6"
    assert gia.da_nhan["lang"] == "vi"        # params vẫn nguyên


def test_load_tat_ba_buoc_tien_xu_ly_khi_yaml_khong_noi_gi(monkeypatch):
    """Mặc định của paddle 3.x là BẬT cả ba, mỗi bước là một model tải thêm."""
    gia = _cai_paddleocr_gia(monkeypatch)

    PaddleOcrRunner().load(_spec_voi_source({}, params={}))

    assert gia.da_nhan == {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }


def test_load_khong_gui_lang_khi_yaml_khong_khai(monkeypatch):
    """`lang` phải vắng mặt hẳn, không được mặc định "vi".

    Paddle 3.x ghép (lang, ocr_version) thành một cặp: `lang="vi"` với
    PP-OCRv4 là ValueError ngay lúc load, chứ không âm thầm rơi về latin như
    bản 2.x. Mặc định "vi" ở runner sẽ làm mọi model không phải v5/v6 chết
    ngay khi nạp, vì một giá trị không ai khai.
    """
    gia = _cai_paddleocr_gia(monkeypatch)

    PaddleOcrRunner().load(_spec_voi_source({"ocr_version": "PP-OCRv4"}, params={}))

    assert "lang" not in gia.da_nhan
    assert gia.da_nhan["ocr_version"] == "PP-OCRv4"


def test_load_keu_len_khi_source_dung_ten_khoa_cua_paddle_2x(monkeypatch):
    """rec_model_dir & friends đã bị gỡ khỏi constructor 3.x.

    Truyền thẳng xuống sẽ là TypeError khó hiểu; im lặng bỏ qua thì cấu hình
    trỏ model tiếng Việt riêng không có tác dụng mà không ai biết.
    """
    import structlog.testing

    _cai_paddleocr_gia(monkeypatch)
    spec = _spec_voi_source({
        "rec_model_dir": "/w/vi_rec_infer",
        "rec_char_dict_path": "/w/vi_dict.txt",
    })

    with structlog.testing.capture_logs() as logs:
        PaddleOcrRunner().load(spec)

    canh_bao = [d for d in logs if d["log_level"] == "warning"]
    assert canh_bao, "khoá của bản 2.x bị bỏ qua mà không cảnh báo"
    assert set(canh_bao[0]["bo_qua"]) == {"rec_model_dir", "rec_char_dict_path"}


def test_load_keu_len_khi_source_khai_thu_paddle_khong_nap_duoc(monkeypatch):
    """`{type: hf, repo: ...}` là mô tả HF — paddle không nạp từ đó.

    Im lặng bỏ qua chính là lỗi ban đầu: yaml hứa PP-OCRv4, host phục vụ
    PP-OCRv3 latin, không chỗ nào nói ra.
    """
    import structlog.testing

    _cai_paddleocr_gia(monkeypatch)
    spec = _spec_voi_source({"type": "hf", "repo": "PaddlePaddle/PP-OCRv4"})

    with structlog.testing.capture_logs() as logs:
        PaddleOcrRunner().load(spec)

    canh_bao = [d for d in logs if d["log_level"] == "warning"]
    assert canh_bao, "source bị bỏ qua mà không cảnh báo"
    assert set(canh_bao[0]["bo_qua"]) == {"type", "repo"}
    assert canh_bao[0]["model_id"] == "ppocr-v6"
