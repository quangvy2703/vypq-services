#!/usr/bin/env bash
# Kiểm nhanh dashboard sau `docker compose up`: đăng nhập được, và KHÔNG có
# đường vòng nào bỏ qua mật khẩu.
set -euo pipefail

BASE="${DASHBOARD_URL:-http://localhost:3001}"
PASSWORD="${DASHBOARD_PASSWORD:?can dat DASHBOARD_PASSWORD}"
COOKIES="$(mktemp)"
trap 'rm -f "$COOKIES"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "1/5 chưa đăng nhập thì /api/hosts phải trả 401"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/hosts")
[ "$code" = "401" ] || fail "/api/hosts trả $code, phải là 401"

echo "2/5 trang bị đẩy về /login"
location=$(curl -s -o /dev/null -w '%{redirect_url}' "$BASE/hosts")
case "$location" in *"/login") ;; *) fail "/hosts chuyển tới '$location', phải tới /login";; esac

echo "3/5 sai mật khẩu bị từ chối"
code=$(curl -s -o /dev/null -w '%{http_code}' -F "password=sai-be-bet" "$BASE/api/login")
[ "$code" = "401" ] || fail "đăng nhập sai trả $code, phải là 401"

echo "4/5 đúng mật khẩu thì lấy được cookie phiên"
curl -s -c "$COOKIES" -o /dev/null -F "password=$PASSWORD" "$BASE/api/login"
grep -q vypq_session "$COOKIES" || fail "không nhận được cookie phiên"

echo "5/5 đã đăng nhập thì đọc được host qua BFF"
body=$(curl -s -b "$COOKIES" "$BASE/api/hosts")
echo "$body" | grep -q '"hosts"' || fail "/api/hosts trả: $body"
echo "$body" | grep -q '"token"' && fail "/api/hosts rò token của máy GPU ra trình duyệt"

echo "OK — dashboard chạy đúng và không rò token."
