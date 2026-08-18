from model_host.runners.fake import FakeAsrRunner, FakeOcrRunner

RUNNERS: dict[str, type] = {
    "fake": FakeOcrRunner,
    "fake-asr": FakeAsrRunner,
}


def _register_optional() -> None:
    """Đăng ký các runner thật.

    Chúng LUÔN được đăng ký, kể cả khi thư viện ML vắng mặt: import nặng nằm
    trong `load()` nên module này import được ở mọi máy. Đó là chủ ý — thiếu thư
    viện thì `load()` ném, registry cô lập model đó, đánh dấu unavailable và trả
    503 rõ ràng, trong khi các model khác chạy bình thường. Nếu ngược lại, không
    đăng ký runner, thì `acquire()` trả 500 "không biết runner", lặp lại mãi và
    không bao giờ đánh dấu unavailable — tệ hơn hẳn.

    `try/except ImportError` dưới đây chỉ phòng trường hợp chính file runner
    hỏng (ví dụ ai đó thêm import nặng lên top level).
    """
    try:
        from model_host.runners.paddle import PaddleOcrRunner
    except ImportError:
        return
    RUNNERS["paddle"] = PaddleOcrRunner


_register_optional()
