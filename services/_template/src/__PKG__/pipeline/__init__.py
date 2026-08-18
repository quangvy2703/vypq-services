"""Pipeline mặc định: không biến đổi gì. Service cụ thể tự thay bằng logic của mình."""


def prepare_input(data: bytes, **_kwargs):
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Prepared:
        data: bytes
        scale: float = 1.0

    return Prepared(data=data)
