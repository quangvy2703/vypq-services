from model_host.runners.fake import FakeAsrRunner, FakeOcrRunner

RUNNERS: dict[str, type] = {
    "fake": FakeOcrRunner,
    "fake-asr": FakeAsrRunner,
}
