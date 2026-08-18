#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "dùng: $0 <slug> <task: ocr|asr> [port]" >&2
  exit 2
fi

SLUG="$1"
TASK="$2"
PORT="${3:-8010}"
PKG="${SLUG}_service"
TASKUPPER="$(echo "$TASK" | tr '[:lower:]' '[:upper:]')"
TITLE="$(echo "${TASK:0:1}" | tr '[:lower:]' '[:upper:]')${TASK:1}"
RAWOUT="Raw${TITLE}Output"
RESP="${TITLE}Response"
BACKEND="${TITLE}Backend"
HANDLER="${TITLE}Handler"
SETTINGS="${TITLE}Settings"
WORKERHANDLER="${TITLE}WorkerHandler"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/services/_template"
DST="$ROOT/services/$SLUG"

if [[ -e "$DST" ]]; then
  echo "services/$SLUG đã tồn tại — dừng lại để không ghi đè" >&2
  exit 1
fi

cp -R "$SRC" "$DST"
mv "$DST/src/__PKG__" "$DST/src/$PKG"

find "$DST" -type f -print0 | while IFS= read -r -d '' file; do
  sed -i '' \
    -e "s/__PKG__/$PKG/g" \
    -e "s/__SLUG__/$SLUG/g" \
    -e "s/__TASKUPPER__/$TASKUPPER/g" \
    -e "s/__RAWOUT__/$RAWOUT/g" \
    -e "s/__RESP__/$RESP/g" \
    -e "s/__BACKEND__/$BACKEND/g" \
    -e "s/__HANDLER__/$HANDLER/g" \
    -e "s/__SETTINGS__/$SETTINGS/g" \
    -e "s/__WORKERHANDLER__/$WORKERHANDLER/g" \
    -e "s/__TASK__/$TASK/g" \
    -e "s/__PORT__/$PORT/g" \
    "$file"
done

# Đăng ký member mới vào workspace root, nếu không venv sẽ không có gói này.
if ! grep -q "\"$SLUG-service\"" "$ROOT/pyproject.toml"; then
  sed -i '' \
    -e "s|^    # <<< workspace members\$|    \"$SLUG-service\",\n    # <<< workspace members|" \
    -e "s|^# <<< workspace sources\$|$SLUG-service = { workspace = true }\n# <<< workspace sources|" \
    "$ROOT/pyproject.toml"
fi
uv sync --project "$ROOT" >/dev/null

# Thứ tự import phụ thuộc tên task (vypq_contracts.$TASK sắp xen giữa các import
# khác), nên template không thể có sẵn thứ tự đúng cho mọi tên. Để ruff tự sắp.
uv run --project "$ROOT" ruff check --fix "$DST" >/dev/null 2>&1 || true

echo "đã tạo services/$SLUG (task=$TASK, port=$PORT)"
echo "bước tiếp: viết pipeline và runner tương ứng, rồi chạy: uv run pytest services/$SLUG"
