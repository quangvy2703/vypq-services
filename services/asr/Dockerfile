FROM python:3.12-slim

# Service này không chạy model, chỉ gọi model-host qua HTTP — không cần CUDA/GPU
# base image như apps/model-host/Dockerfile.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY packages ./packages
COPY services/asr ./services/asr
# Kèm cả nhóm dev để chạy được test ngay trên image. Bản build thuần production
# thì thêm --no-dev cho ảnh gọn hơn.
RUN uv sync --frozen --package asr-service --group dev

ENV VYPQ_HOSTS_PATH=/app/services/asr/config.yaml \
    VYPQ_PORT=8002
EXPOSE 8002
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:8002/health || exit 1
CMD ["uv", "run", "uvicorn", "asr_service.main:app", "--host", "0.0.0.0", "--port", "8002"]
