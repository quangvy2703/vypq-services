FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

# KHÔNG apt-get install python3.12: Ubuntu 22.04 chỉ có python3.10 trong repo
# mặc định nên lệnh đó làm hỏng build. Để uv tự tải CPython 3.12 theo
# .python-version — cùng đúng phiên bản đang chạy ở máy dev.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY packages ./packages
COPY apps/model-host ./apps/model-host
# Kèm cả nhóm dev để chạy được test chậm ngay trên máy GPU (bước 7). Bản build
# thuần production thì thêm --no-dev cho ảnh gọn hơn.
RUN uv sync --frozen --package model-host --extra gpu --group dev

ENV VYPQ_MODELS_PATH=/app/apps/model-host/models.yaml \
    VYPQ_PORT=9000
EXPOSE 9000
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:9000/health || exit 1
CMD ["uv", "run", "uvicorn", "model_host.main:app", "--host", "0.0.0.0", "--port", "9000"]
