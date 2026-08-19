#!/usr/bin/env bash
set -euo pipefail
GW=${GW:-http://localhost:8080}
# Token của GATEWAY (Authorization: Bearer ...) — khác với VYPQ_TOKEN bên
# dưới, vốn là token của model-host được đăng ký. Hai bí mật độc lập, đừng
# lẫn: gateway kiểm token này trên mọi route /v1, model-host kiểm VYPQ_TOKEN
# trên route /v1 của chính nó.
GW_TOKEN=${VYPQ_GATEWAY_TOKEN:?dat VYPQ_GATEWAY_TOKEN}
AUTH=(-H "Authorization: Bearer $GW_TOKEN")

echo "== gateway sống =="
curl -fsS "$GW/health" >/dev/null

echo "== /v1 không token bị từ chối =="
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$GW/v1/hosts" \
  -H 'Content-Type: application/json' -d '{"name":"khong-token","url":"http://x:9000"}')
[ "$CODE" = "401" ] || { echo "kỳ vọng 401, nhận $CODE"; exit 1; }

echo "== đăng ký host =="
curl -fsS -X POST "$GW/v1/hosts" "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d "{\"name\":\"gpu-dev\",\"url\":\"${HOST_URL:?dat HOST_URL}\",\"token\":\"${VYPQ_TOKEN:?dat VYPQ_TOKEN}\"}" >/dev/null

echo "== chờ poller thấy host =="
for _ in $(seq 1 20); do
  curl -fsS "$GW/v1/hosts" "${AUTH[@]}" | grep -q '"healthy":true' && break
  sleep 2
done
curl -fsS "$GW/v1/hosts" "${AUTH[@]}" | grep -q '"healthy":true'

echo "== discovery có token, listing thì không =="
curl -fsS "$GW/v1/discovery/hosts" "${AUTH[@]}" | grep -q "$VYPQ_TOKEN"
! curl -fsS "$GW/v1/hosts" "${AUTH[@]}" | grep -q "$VYPQ_TOKEN"

echo "== service tự khai capability =="
curl -fsS "$GW/v1/services" "${AUTH[@]}" | grep -q '"invoke_path"'

echo "== gọi OCR qua gateway =="
curl -fsS "${AUTH[@]}" -F service=ocr -F file=@tests/fixtures/sample.png "$GW/v1/invoke/upload" | grep -q full_text

echo "== lần chạy đó vào lịch sử =="
curl -fsS "$GW/v1/runs?limit=1" "${AUTH[@]}" | grep -q '"status":"ok"'

echo "TẤT CẢ ĐẠT"
