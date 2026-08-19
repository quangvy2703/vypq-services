# Dashboard

Trang quản lí trung tâm: cắm máy GPU thuê, xem service, chạy thử OCR/ASR, tra lịch sử.

## Vì sao có tầng BFF

Gateway đòi bearer token trên mọi route `/v1`. Token đó cho phép đọc
`/v1/discovery/hosts` — nơi chứa token của **mọi máy GPU đang thuê**. Nếu trình duyệt
giữ token gateway thì bất kỳ ai mở DevTools cũng lấy được chuỗi đó.

Nên: trình duyệt chỉ nói chuyện với server Next (cùng origin, dùng cookie phiên), và
server Next mới gắn `GATEWAY_TOKEN` gọi sang gateway. Token không bao giờ rời tiến trình
Node. Bài kiểm `tests/unit/client-boundary.test.ts` canh đúng ranh giới này.

Hệ quả: **dashboard phải có mật khẩu riêng.** Không có nó, cổng 3001 chính là một proxy
công khai vào một gateway có xác thực.

## Biến môi trường

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `GATEWAY_URL` | không (mặc định `http://localhost:8080`) | URL nội bộ tới gateway |
| `GATEWAY_TOKEN` | **có** | phải trùng `VYPQ_TOKEN` của gateway |
| `DASHBOARD_PASSWORD` | **có** | mật khẩu dùng chung để vào dashboard |
| `SESSION_SECRET` | **có** | khoá ký cookie phiên, sinh bằng `openssl rand -hex 32` |

Thiếu bất kỳ biến bắt buộc nào thì dashboard ném lỗi thay vì chạy tiếp — giống
`GatewaySettings._token_must_not_be_empty`.

## Chạy

```bash
cd apps/dashboard
cp .env.example .env.local   # điền ba bí mật
pnpm install && pnpm dev     # http://localhost:3001
```

Trong compose: `docker compose -f infra/compose/docker-compose.dev.yml up dashboard`.
Cổng 3001 vì 3000 đã là Grafana.

## Các trang

- **Model Hosts** — cắm URL ngrok + token của máy GPU vừa thuê. Gateway poll mỗi 15 giây
  và coi host là chết sau 45 giây, nên host mới cắm cần khoảng một chu kỳ để chuyển xanh.
- **Services** — service nào gateway liên hệ được, capability và model mặc định của nó.
  Service có `info = null` hiện "Chưa liên hệ được" và **không** bị đoán task.
- **Playground** — upload ảnh/âm thanh, chạy một hoặc nhiều model, xem bbox overlay
  (OCR) hoặc transcript có mốc thời gian (ASR). Tick thêm model ở "So sánh thêm với" để
  chạy song song và xem kết quả cạnh nhau kèm thống kê mô tả và độ trễ thật.
- **Lịch sử** — lọc theo service/trạng thái/trace, phân trang. Bấm `trace_id` ra mọi run
  cùng trace: đó là cách nhìn shadow-run (một event, nhiều model version).

## Giới hạn đã biết

- **Chấm điểm không nằm ở đây.** So sánh trong Playground là **mô tả** (số vùng chữ, số ký
  tự, độ tin cậy trung bình, độ trễ), không phải điểm số. CER/WER/IoU cần ground truth và
  là việc của Plan C.
- **Run sync không lưu ảnh gốc.** `SyncProxy.invoke` ghi `input_uri = null`, nên trang chi
  tiết run vẽ bbox trên nền trắng theo khung suy từ chính các polygon. Chỉ Playground —
  nơi trình duyệt còn giữ file — mới overlay lên ảnh thật.
- **Không có đường async trên UI.** `POST /v1/invoke` mode async cần `input_uri` (một URI
  gateway tải được), còn dashboard gửi file trực tiếp. Muốn chạy async thì publish
  `InferenceRequested` vào Kafka.
- **Một mật khẩu dùng chung**, không có khái niệm người dùng hay phân quyền. Payload cookie
  chỉ chứa hạn dùng (12 giờ).
- **`pnpm test:e2e` không chạy cùng entrypoint với production.** Bộ e2e (Playwright) khởi
  động dashboard bằng `next start`, trong khi image Docker chạy `node server.js` từ cây
  `.next/standalone` (do `output: "standalone"` trong `next.config.ts`). Hai đường khởi
  động này không tương đương — `next start` còn in cảnh báo "does not work with output:
  standalone" khi chạy trên build đã bật standalone. Vì vậy chỉ `scripts/smoke-dashboard.sh`
  chạy trên image Docker thật (`docker build` rồi `docker compose up`) mới thật sự kiểm
  được entrypoint sẽ chạy ở production; `pnpm test:e2e` xanh không đủ để suy ra
  `node server.js` cũng phục vụ đúng.
