from model_host.runners.fake import FakeAsrRunner, FakeOcrRunner

RUNNERS: dict[str, type] = {
    "fake": FakeOcrRunner,
    "fake-asr": FakeAsrRunner,
}


def _register_optional() -> None:
    # Runner thật cần thư viện nặng, chỉ có trên máy GPU. Vắng mặt thì bỏ qua
    # để host vẫn chạy được ở chế độ fake trên máy dev.
    try:
        from model_host.runners.paddle import PaddleOcrRunner
    except ImportError:
        return
    RUNNERS["paddle"] = PaddleOcrRunner


_register_optional()
