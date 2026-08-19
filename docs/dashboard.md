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
| `DASHBOARD_AUTH` | không (mặc định `on`) | đặt `off` để bỏ hẳn cổng mật khẩu |

Thiếu bất kỳ biến bắt buộc nào thì dashboard ném lỗi thay vì chạy tiếp — giống
`GatewaySettings._token_must_not_be_empty`.

### `DASHBOARD_AUTH=off`

Bỏ hẳn trang đăng nhập: mọi trang và mọi `/api/*` vào thẳng. `DASHBOARD_PASSWORD` và
`SESSION_SECRET` lúc đó không cần nữa; `GATEWAY_TOKEN` thì vẫn bắt buộc vì không có nó
dashboard chẳng gọi được gì.

**Chỉ dùng khi cổng 3001 không ai ngoài với tới được.** Dashboard cầm `GATEWAY_TOKEN`, và
token đó đọc được endpoint discovery của gateway — nơi chứa token của **mọi máy GPU đang
thuê**. Tắt xác thực là biến cổng 3001 thành đường vào thẳng chỗ đó.

Cờ này so khớp **chính xác** chuỗi `off`. Mọi giá trị khác — `false`, `0`, hay một lỗi gõ —
đều giữ nguyên xác thực, và vắng mặt cũng vậy: quên cấu hình không bao giờ được biến thành
mở khoá. `scripts/stack.sh` đặt sẵn `off` trong `infra/compose/.env` cho máy local; đổi
thành `on` trước khi đưa ra ngoài.

## Chạy

```bash
cd apps/dashboard
# scripts/stack.sh dev tự ghi .env.local với token khớp gateway
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
- **Trang không tự làm mới.** Mọi trang đều `force-dynamic`, nhưng không có polling nào ở
  phía trình duyệt: chữ "3 phút trước" tự nhịp lại, còn *trạng thái* host thì không. Cắm
  host xong phải **tải lại trang** mới thấy nó chuyển xanh — gateway poll mỗi 15 giây,
  nhưng dashboard chỉ đọc lại khi có ai đó bảo nó đọc.
- **Tệp chạy thử tối đa 25 MB**, khớp `max_inline_mb` của service. Chặn hai lớp: theo
  `Content-Length` trước khi đọc body, rồi theo kích thước file thật.
- **So sánh nhiều model sinh nhiều `trace_id` khác nhau.** Mỗi model là một lần gọi
  `/v1/invoke/upload` riêng, nên không gom được chúng lại bằng cách bấm `trace_id` như với
  shadow-run. Muốn gom thì phải đi đường async qua Kafka.
- **Độ trễ khi so sánh không so được với nhau.** Các model chạy **song song**
  (`Promise.allSettled`) nên chúng tranh nhau cùng một GPU; `latency_ms` đọc từ bản ghi run
  là số thật của lần chạy đó, nhưng là số đo *dưới tải cạnh tranh*, không phải độ trễ của
  model khi chạy một mình. Dùng nó để thấy "chậm hơn hẳn" thì được, để xếp hạng thì không.
- **Tên service phải khớp giữa hai nơi.** `config/services.yaml` đặt **khoá định tuyến**,
  còn service tự khai `name` qua `/v1/info`. Gateway định tuyến bằng khoá, dashboard cũng
  gọi bằng khoá, nên lệch nhau không còn làm hỏng gì — nhưng gateway sẽ ghi cảnh báo
  `service_name_mismatch`, và hai cái tên khác nhau trong giao diện thì khó đọc.
- **Cố ý ngoài phạm vi, không phải thiếu sót:** trang `models` riêng (danh sách model đã
  hiện đủ trong bảng Host và ô chọn của Playground), trình xem DLQ, và nhúng biểu đồ
  Prometheus/Grafana. Ba thứ đó thuộc bước 10 của lộ trình Plan B và Plan C.
- **Chỉ có `task: ocr` và `asr`.** `Task` trong `packages/vypq-contracts` là enum đóng, nên
  một service khai `task: "ner"` bị gateway từ chối ngay ở bước đọc `/v1/info` và không bao
  giờ xuất hiện trên dashboard. Phần *capability* của dashboard thì đã sẵn sàng cho service
  lạ (`capability_input`/`capability_output` chưa biết đều có đường lui), nhưng `task` thì
  chưa — mở nó ra là thay đổi ở tầng hợp đồng nền tảng, không phải ở đây.
- **`pnpm test:e2e` không chạy cùng entrypoint với production.** Bộ e2e (Playwright) khởi
  động dashboard bằng `next start`, trong khi image Docker chạy `node server.js` từ cây
  `.next/standalone` (do `output: "standalone"` trong `next.config.ts`). Hai đường khởi
  động này không tương đương — `next start` còn in cảnh báo "does not work with output:
  standalone" khi chạy trên build đã bật standalone. Vì vậy chỉ `scripts/smoke-dashboard.sh`
  chạy trên image Docker thật (`docker build` rồi `docker compose up`) mới thật sự kiểm
  được entrypoint sẽ chạy ở production; `pnpm test:e2e` xanh không đủ để suy ra
  `node server.js` cũng phục vụ đúng.
