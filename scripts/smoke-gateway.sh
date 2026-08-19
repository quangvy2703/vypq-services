#!/usr/bin/env bash
set -euo pipefail
GW=${GW:-http://localhost:8080}

echo "== gateway sống =="
curl -fsS "$GW/health" >/dev/null

echo "== đăng ký host =="
curl -fsS -X POST "$GW/v1/hosts" -H 'Content-Type: application/json' \
  -d "{\"name\":\"gpu-dev\",\"url\":\"${HOST_URL:?dat HOST_URL}\",\"token\":\"${VYPQ_TOKEN:?dat VYPQ_TOKEN}\"}" >/dev/null

echo "== chờ poller thấy host =="
for _ in $(seq 1 20); do
  curl -fsS "$GW/v1/hosts" | grep -q '"healthy":true' && break
  sleep 2
done
curl -fsS "$GW/v1/hosts" | grep -q '"healthy":true'

echo "== discovery có token, listing thì không =="
curl -fsS "$GW/v1/discovery/hosts" | grep -q "$VYPQ_TOKEN"
! curl -fsS "$GW/v1/hosts" | grep -q "$VYPQ_TOKEN"

echo "== service tự khai capability =="
curl -fsS "$GW/v1/services" | grep -q '"invoke_path"'

echo "== gọi OCR qua gateway =="
curl -fsS -F service=ocr -F file=@tests/fixtures/sample.png "$GW/v1/invoke/upload" | grep -q full_text

echo "== lần chạy đó vào lịch sử =="
curl -fsS "$GW/v1/runs?limit=1" | grep -q '"status":"ok"'

echo "TẤT CẢ ĐẠT"
