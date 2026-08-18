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
COPY services/__SLUG__ ./services/__SLUG__
# Kèm cả nhóm dev để chạy được test ngay trên image. Bản build thuần production
# thì thêm --no-dev cho ảnh gọn hơn.
RUN uv sync --frozen --package __SLUG__-service --group dev

ENV VYPQ_HOSTS_PATH=/app/services/__SLUG__/config.yaml \
    VYPQ_PORT=__PORT__
EXPOSE __PORT__
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:__PORT__/health || exit 1
CMD ["uv", "run", "uvicorn", "__PKG__.main:app", "--host", "0.0.0.0", "--port", "__PORT__"]
