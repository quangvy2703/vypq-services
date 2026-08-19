import secrets

from fastapi import Header
from vypq_contracts.common import ErrorCode
from vypq_core.errors import ServiceError


def make_token_dependency(expected: str):
    async def require_token(authorization: str = Header(default="")) -> None:
        prefix = "Bearer "
        supplied = authorization[len(prefix):] if authorization.startswith(prefix) else ""
        # compare_digest thay vì ==: so sánh chuỗi thường thoát sớm ở byte đầu
        # khác nhau. Cùng lý do như model-host: đây là thứ duy nhất chặn giữa
        # Internet và toàn bộ danh sách host + token của các máy GPU đang thuê.
        if not secrets.compare_digest(supplied, expected):
            raise ServiceError(ErrorCode.BAD_INPUT, "token không hợp lệ", http_status=401)

    return require_token
