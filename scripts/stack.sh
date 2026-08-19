#!/usr/bin/env bash
# Bật/tắt stack dev. Sinh bí mật một lần rồi giữ nguyên trong infra/compose/.env
# (đã bị .gitignore bắt) — nếu sinh lại mỗi lần thì SESSION_SECRET đổi và mọi
# phiên đăng nhập đang mở bị đá ra sau mỗi lần restart.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT/infra/compose"
ENV_FILE="$COMPOSE_DIR/.env"
# docker compose tự đọc file .env nằm cạnh compose file, nên không cần export gì.
DC=(docker compose -f "$COMPOSE_DIR/docker-compose.dev.yml")

# Hạ tầng + hai thứ tự viết. Không bật prometheus/grafana/redpanda-console mặc
# định: chúng không cần cho việc dùng dashboard, chỉ tốn RAM.
CORE=(postgres redpanda gateway dashboard)

die() { echo "LỖI: $*" >&2; exit 1; }

sinh_env() {
  [ -f "$ENV_FILE" ] && return 0
  command -v openssl >/dev/null || die "cần openssl để sinh bí mật"
  echo "Chưa có $ENV_FILE — sinh bí mật mới."
  local matkhau="${DASHBOARD_PASSWORD:-$(openssl rand -hex 8)}"
  cat > "$ENV_FILE" <<EOF
# Sinh tự động bởi scripts/stack.sh. File này KHÔNG vào git.
# Token gateway: dashboard và mọi service dùng nó để gọi /v1/* của gateway.
VYPQ_TOKEN=$(openssl rand -hex 16)
# Mật khẩu vào dashboard ở http://localhost:3001
DASHBOARD_PASSWORD=$matkhau
# Khoá ký cookie phiên. Đổi giá trị này là đá mọi phiên đang đăng nhập.
SESSION_SECRET=$(openssl rand -hex 32)
EOF
  chmod 600 "$ENV_FILE"
}

# .env.local cho `pnpm dev` chạy trên máy chủ. Sinh từ cùng nguồn với compose,
# vì GATEWAY_TOKEN phải TRÙNG VYPQ_TOKEN — gõ tay hai chỗ là cách chắc chắn để
# nhận 401 rồi ngồi đoán tại sao.
dong_bo_env_local() {
  local dest="$ROOT/apps/dashboard/.env.local"
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
  cat > "$dest" <<EOF
# Sinh tự động bởi scripts/stack.sh từ infra/compose/.env — đừng sửa tay.
# localhost chứ không phải "gateway": bản dev chạy ngoài mạng docker.
GATEWAY_URL=http://localhost:8080
GATEWAY_TOKEN=$VYPQ_TOKEN
DASHBOARD_PASSWORD=$DASHBOARD_PASSWORD
SESSION_SECRET=$SESSION_SECRET
EOF
  chmod 600 "$dest"
}

cho_khoe() {
  local ten="$1" giay=0
  printf 'chờ %s' "$ten"
  # 90 giây: gateway phải chạy xong migration alembic rồi mới nhận /health.
  while [ "$giay" -lt 90 ]; do
    case "$("${DC[@]}" ps --format '{{.Service}} {{.Status}}' 2>/dev/null | grep "^$ten " || true)" in
      *healthy*) echo " ✓"; return 0 ;;
      *Exited*|*Restarting*)
        echo " ✗"
        "${DC[@]}" logs --tail 25 "$ten"
        die "$ten không lên được"
        ;;
    esac
    printf '.'; sleep 2; giay=$((giay + 2))
  done
  echo " ✗"; die "$ten quá 90s vẫn chưa khoẻ"
}

cmd_up() {
  sinh_env
  dong_bo_env_local
  "${DC[@]}" up -d --build "${CORE[@]}"
  cho_khoe postgres
  cho_khoe redpanda
  cho_khoe gateway
  # dashboard không khai healthcheck nên hỏi thẳng nó.
  local giay=0
  printf 'chờ dashboard'
  until curl -fsS -o /dev/null "http://localhost:3001/login"; do
    [ "$giay" -ge 60 ] && { echo " ✗"; "${DC[@]}" logs --tail 25 dashboard; die "dashboard không phản hồi"; }
    printf '.'; sleep 2; giay=$((giay + 2))
  done
  echo " ✓"

  # shellcheck disable=SC1090
  . "$ENV_FILE"
  cat <<EOF

  Dashboard   http://localhost:3001     mật khẩu: $DASHBOARD_PASSWORD
  Gateway     http://localhost:8080     token:    $VYPQ_TOKEN

  Playground còn trống cho tới khi có service chạy — khai chúng vào
  apps/gateway/config/services.yaml. Trang không tự làm mới: cắm host xong
  phải tải lại trang mới thấy nó chuyển xanh.
EOF
}

cmd_dev() {
  sinh_env
  dong_bo_env_local
  # Chỉ hạ tầng + gateway; dashboard chạy bằng pnpm dev để có hot reload.
  "${DC[@]}" up -d --build postgres redpanda gateway
  cho_khoe postgres; cho_khoe redpanda; cho_khoe gateway
  echo
  echo "Hạ tầng sẵn sàng. Chạy dashboard có hot reload:"
  echo "  cd apps/dashboard && pnpm install && pnpm dev"
  echo "Đã ghi apps/dashboard/.env.local với token khớp gateway."
}

cmd_down()   { "${DC[@]}" down "$@"; }
cmd_ps()     { "${DC[@]}" ps; }
cmd_logs()   { "${DC[@]}" logs -f --tail 50 "${@:-gateway}"; }
cmd_smoke()  { set -a; . "$ENV_FILE"; set +a; "$ROOT/scripts/smoke-dashboard.sh"; }

case "${1:-up}" in
  up)    shift; cmd_up "$@" ;;
  dev)   shift; cmd_dev "$@" ;;
  down)  shift; cmd_down "$@" ;;
  ps)    shift; cmd_ps "$@" ;;
  logs)  shift; cmd_logs "$@" ;;
  smoke) shift; cmd_smoke "$@" ;;
  *)
    cat <<EOF
Cách dùng: scripts/stack.sh <lệnh>

  up      dựng cả stack trong docker, in ra URL và mật khẩu   (mặc định)
  dev     chỉ dựng hạ tầng + gateway, để chạy pnpm dev ngoài
  down    tắt (thêm -v để xoá luôn dữ liệu postgres)
  ps      trạng thái container
  logs    theo dõi log, mặc định gateway. vd: logs dashboard
  smoke   chạy scripts/smoke-dashboard.sh với bí mật đã sinh
EOF
    exit 1
    ;;
esac
