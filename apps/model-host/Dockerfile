FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.12 python3-pip libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps/model-host ./apps/model-host
RUN uv sync --frozen --package model-host --extra gpu

ENV VYPQ_MODELS_PATH=/app/apps/model-host/models.yaml \
    VYPQ_PORT=9000
EXPOSE 9000
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:9000/health || exit 1
CMD ["uv", "run", "uvicorn", "model_host.main:app", "--host", "0.0.0.0", "--port", "9000"]
