from fastapi import Header
from vypq_contracts.common import ErrorCode
from vypq_core.errors import ServiceError


def make_token_dependency(expected: str):
    async def require_token(authorization: str = Header(default="")) -> None:
        prefix = "Bearer "
        supplied = authorization[len(prefix):] if authorization.startswith(prefix) else ""
        if supplied != expected:
            raise ServiceError(ErrorCode.BAD_INPUT, "token không hợp lệ", http_status=401)

    return require_token
