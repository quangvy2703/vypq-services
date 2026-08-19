FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY packages ./packages
COPY apps/gateway ./apps/gateway
RUN uv sync --frozen --package gateway

ENV VYPQ_PORT=8080 VYPQ_SERVICES_PATH=/app/apps/gateway/config/services.yaml
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:8080/health || exit 1
# Gọi thẳng uvicorn trong .venv, KHÔNG qua "uv run": uv run giải lại phụ thuộc
# lúc khởi động và kéo cả nhóm `dev` của workspace, trong đó có model-host và
# hai service — những thứ image này cố tình không chứa. Kết quả là image build
# xong vẫn chết ngay khi start với "references a workspace ... but is not a
# workspace member". Container không phải chỗ để giải phụ thuộc lần nữa: đã
# sync ở bước build rồi.
CMD [".venv/bin/uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
