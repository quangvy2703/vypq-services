# Thiết kế: Nền tảng AI Services (vypq-services)

- **Ngày:** 2026-08-18
- **Trạng thái:** Đã duyệt, chờ lập implementation plan

## 1. Mục tiêu

Dựng một nền tảng để host nhiều mô hình AI (khởi đầu: OCR, ASR) thành các service độc lập,
kèm một trang quản lí trung tâm để test và để **so sánh điểm số giữa model open-source và
model tự fine-tune**. Dữ liệu huấn luyện được thu thập bởi một repo crawler tách biệt.

### Tiêu chí thành công

1. Thêm một model service mới không phải sửa code của gateway hay dashboard.
2. Thêm một model version mới (checkpoint fine-tune) chỉ sửa **một** file YAML, không rebuild image.
3. So sánh được 2+ model version trên cùng một dataset có nhãn, xem được cả điểm tổng hợp
   lẫn từng item sai.
4. Mỗi service build, chạy, test được độc lập, và test được **không cần GPU**.

### Ngoài phạm vi (YAGNI)

- Kubernetes, auto-scaling, multi-tenant, phân quyền người dùng.
- Training pipeline. Nền tảng này chỉ *phục vụ* và *đánh giá* model, không train.
- Quản lí thử nghiệm kiểu MLflow/W&B.

## 2. Cấu trúc repo

Hai repo, cùng cấp trong `~/WorkingSpace/`:

- `vypq-services/` — monorepo: shared packages, model services, model-host, gateway,
  evaluator, dashboard, infra.
- `vypq-crawler/` — repo riêng: thu thập dữ liệu web.

Tách vì crawler có lifecycle khác hẳn (chạy theo lịch, phụ thuộc browser/proxy, scale theo
I/O chứ không theo GPU). Hai repo nối nhau qua MinIO và Redpanda, không gọi API trực tiếp.

## 3. Kiến trúc

Hai máy: **máy ứng dụng** (CPU) chạy toàn bộ nền tảng, **máy GPU** chỉ chạy `model-host`.

```
        MÁY ỨNG DỤNG (CPU)                              MÁY GPU
┌───────────────────────────────────┐          ┌──────────────────────┐
│ Dashboard ─▶ Gateway ─┬─ HTTP ────┼─▶ ocr-service ──HTTP──▶ model-host
│                       └─ publish ─┼─▶ Redpanda   │          ├ paddleocr
│                                   │      │       │          ├ vietocr
│  Evaluator ─────────publish───────┼──────┘       │          └ vietocr-ft-*
│                                   │      ▼       │              │
│  Postgres (registry/runs/eval)    │  ocr-worker ─┼──────────────┘
│  MinIO (ảnh, audio, checkpoint)   │              │
└───────────────────────────────────┘          └──────────────────────┘
```

### 3.1 Phân vai

| Thành phần | Chạy ở đâu | Giữ state? | Trách nhiệm |
|---|---|---|---|
| `model-host` | Máy GPU | Có (weights trong VRAM) | Load model, chạy inference thô |
| `services/*` | Máy ứng dụng | Không | Pre/post-process, map về contract chuẩn |
| `gateway` | Máy ứng dụng | DB | Registry, định tuyến, lịch sử, metrics |
| `evaluator` | Máy ứng dụng | DB | Dataset, metrics, benchmark |

`services/*` **không giữ weights**, chạy CPU, stateless. Nhờ vậy test chạy được trên laptop
không GPU, và scale service = thêm container, không đụng đến VRAM.

### 3.2 model-host — nguồn sự thật về model

**Máy GPU là tài nguyên thuê theo giờ, không phải hạ tầng cố định.** Nó sinh ra rồi biến mất,
URL đổi mỗi lần thuê, và có thể có nhiều máy hoặc nhiều GPU cùng lúc. Toàn bộ thiết kế phía
dưới coi "host biến mất" là sự kiện bình thường, không phải lỗi.

`apps/model-host/models.yaml` là **nơi duy nhất** khai báo model nào tồn tại:

```yaml
vram_budget_mb: 20000
models:
  - id: paddleocr-v4-vi
    task: ocr
    kind: opensource
    runner: paddle
    source: {type: hf, repo: PaddlePaddle/PP-OCRv4}
    pinned: true                # không bao giờ bị evict
  - id: vietocr-ft-invoice-20260801
    task: ocr
    kind: finetuned
    runner: vietocr
    base: vietocr-base
    source: {type: s3, uri: s3://models/ocr/vietocr-ft-invoice-20260801}
    trained_on: invoice-vi-v2
```

**Thêm model fine-tune = thêm một khối YAML + upload checkpoint lên MinIO.** Không sửa code
service, không sửa gateway, không sửa dashboard.

Thông tin model lan truyền theo chuỗi, mỗi mắt xích chỉ đọc mắt trước:

```
model-host/models.yaml → GET /v1/models → services → gateway GET /info
                                                        → bảng model_versions → dashboard
```

`model-host` quản lí VRAM: lazy load khi có request đầu tiên, evict LRU khi vượt
`vram_budget_mb`, model `pinned` miễn trừ. Đây là nơi duy nhất trong hệ thống biết đến VRAM.

**Hai kho lưu trữ tách biệt.** Máy thuê có Internet ra ngoài nhưng không với vào được MinIO
trong mạng nội bộ, mà mỗi lần thuê máy mới nó phải tải lại vài GB weights:

| Kho | Nội dung | Ai đọc |
|---|---|---|
| MinIO nội bộ | ảnh, audio, output, dataset | máy ứng dụng |
| Object store ngoài (Cloudflare R2) | checkpoint fine-tune | máy GPU thuê |

Chọn R2 vì egress miễn phí — tải weights lặp lại mỗi lần thuê máy chính là egress, S3 sẽ tính
tiền đúng vào chỗ đó. Model open-source kéo thẳng từ HuggingFace, không cần kho riêng.

API:

- `POST /v1/infer` → `{model_id, input: {uri | b64}, params}` → `{model_id, output, timing}`
- `GET /v1/models` → danh sách model, task, kind, trạng thái loaded
- `GET /health`, `GET /ready`

**Truyền dữ liệu qua MinIO URI, không nhét base64 vào JSON.** Cả hai máy đều truy cập được
MinIO; base64 làm phình 33% và rất tệ với file audio dài. Dashboard upload lên MinIO trước,
sau đó chỉ có URI đi qua mạng. Trường `b64` chỉ dành cho debug thủ công.

### 3.3 Backend cắm được ở service

```python
# services/ocr/src/ocr_service/backend/base.py
class OcrBackend(Protocol):
    async def infer(self, image_uri: str, model_id: str) -> RawOcrOutput: ...
```

- `RemoteBackend` — HTTP tới `model-host`. Dùng trong mọi môi trường thật.
- `FakeBackend` — trả output cố định. Dùng cho unit test, chạy trong CI không cần GPU.

`services/ocr/config.yaml` **không khai báo host cố định** — host thuê theo giờ nên danh sách
là động, lấy từ gateway (mục 3.4):

```yaml
host_discovery:
  source: gateway              # gateway | static
  url: http://gateway:8080/v1/hosts
  refresh_s: 15
  fallback_static: []          # dùng khi dev offline
default_model: paddleocr-v4-vi
transfer: inline               # inline | uri
timeout_s: 60
max_inline_mb: 25
```

`vypq_core.host_registry` cung cấp hai nguồn (`static`, `discovery`) sau cùng một interface,
nên service không phụ thuộc vào sự tồn tại của gateway — chỉ là một URL trong config.

Service lọc model **theo `task` khớp capability của mình** — `services/ocr` chỉ nhận model có
`task: ocr`. Nhờ vậy một model-host phục vụ được nhiều service mà không cần cấu hình chéo.

**Truyền dữ liệu tới model-host** có hai chế độ:

- **`inline` (mặc định)** — gửi file qua `multipart/form-data`. Chạy được ở mọi topology, kể
  cả khi máy GPU không với tới MinIO nội bộ. Dùng multipart chứ không base64: multipart gửi
  binary nguyên vẹn, base64 phình 33%. Trường `b64` chỉ giữ để debug bằng `curl`.
- **`uri`** — model-host tự tải từ MinIO. Chỉ dùng khi máy GPU cùng mạng với máy ứng dụng.

Phần pre/post-processing (deskew, resize, gộp box, sắp thứ tự đọc, chuẩn hoá Unicode) nằm
trong service — có test, có version. Đây là phần quyết định chất lượng OCR không kém model.

### 3.4 Host registry — máy GPU thuê theo giờ

Gateway giữ danh sách host đang sống. Đăng ký lúc chạy, không nằm trong file config:

```bash
curl -X POST localhost:8080/v1/hosts -d '{
  "name": "gpu-1", "url": "https://a1b2.ngrok.app", "token": "..."}'
```

Hoặc dán URL + token vào trang **Model Hosts** trên dashboard.

**Chiều gọi:** gateway *poll ra* model-host (`GET /v1/models` và `/health`, mỗi 15s).
Model-host **không** tự đăng ký ngược về. Lý do: máy ứng dụng cũng nằm sau NAT, còn ngrok chỉ
mở một chiều vào máy GPU — poll ra là chiều duy nhất chạy được mà không phải phơi thêm gì
ra Internet.

- Host quá 45s không phản hồi → `offline`, gỡ khỏi bảng định tuyến.
- Bảng định tuyến: `model_id → [host khoẻ]`. Chọn host **ít request đang chạy nhất**.
- URL ngrok đổi mỗi lần thuê → đăng ký lại, không sửa file, không restart service.

**Nhiều GPU: một container cho mỗi GPU.** Không viết code chia GPU trong `model-host`:

```yaml
model-host-0: {environment: [CUDA_VISIBLE_DEVICES=0], ports: ["9001:9000"]}
model-host-1: {environment: [CUDA_VISIBLE_DEVICES=1], ports: ["9002:9000"]}
```

Mỗi container đăng ký là một host riêng, dùng lại đúng registry vốn đã cần cho nhiều máy.
Một máy 4 GPU và bốn máy 1 GPU trông giống hệt nhau với gateway — không thêm dòng code nào.

**Bảo mật.** ngrok đưa endpoint ra Internet công cộng và URL ngrok bị quét tự động rất nhanh.
`model-host` bắt buộc kiểm bearer token ở middleware và **từ chối khởi động nếu token rỗng**.

### 3.5 Chịu lỗi khi model-host ở máy khác

Máy khác nghĩa là sẽ có lúc mạng đứt hoặc GPU quá tải. Thiết kế bắt buộc có:

- **Timeout** theo từng model, khai trong `config.yaml`.
- **Retry** chỉ với lỗi kết nối và 5xx, tối đa 2 lần, backoff luỹ thừa + jitter.
  Không retry 4xx (input sai thì thử lại vẫn sai).
- **Circuit breaker** theo `(host, model_id)`: mở sau N lỗi liên tiếp, half-open sau T giây.
- **Health poller** — service poll `/health` của model-host, phản ánh vào `/ready` của chính
  nó, gateway thấy service degraded và trả 503 rõ ràng thay vì treo.
- **Kafka worker dừng consume khi circuit mở**, không phải đẩy message vào DLQ.
  Nếu không, một lần GPU sập sẽ đổ toàn bộ hàng đợi vào DLQ và phải xử lý tay hàng nghìn item.
  Worker pause, chờ circuit đóng lại, rồi consume tiếp — message vẫn nằm nguyên trong topic.

### 3.6 Hai transport, một lõi

Mỗi service có hai entrypoint gọi chung một hàm xử lý:

- `main.py` → FastAPI, cho playground và debug (độ trễ thấp).
- `worker.py` → Kafka consumer, cho batch, evaluation, luồng crawler→OCR.

Cả hai gọi `handler.handle(request) -> response`. Thêm transport mới không đụng vào backend.

### 3.7 Event bus

Broker: **Redpanda** (tương thích Kafka API, client `aiokafka`). Chọn vì 1 binary,
không cần JVM/ZooKeeper.

| Topic | Producer | Consumer |
|---|---|---|
| `infer.ocr.requests` | gateway, evaluator, crawler | ocr workers |
| `infer.ocr.results` | ocr workers | gateway, evaluator |
| `infer.ocr.dlq` | consumer helper | thủ công / dashboard |
| `infer.asr.*` | như trên | như trên |
| `crawl.documents.ready` | crawler | gateway |

- Partition key = `trace_id` → mọi event của một request cùng partition, giữ thứ tự.
- Delivery at-least-once. Commit offset **sau khi** xử lý xong. Chống trùng bằng khoá duy
  nhất `(trace_id, model_version_id)` trên bảng `runs`.

**Consumer group và chọn model.** Worker chạy với biến môi trường `MODEL_VERSION`:

- **Không đặt** → group `{service}-default`, phục vụ model mà event chỉ định
  (không có thì dùng `default_model`). Chế độ thường ngày.
- **Có đặt** → group `{service}-{model_version}`, ép dùng đúng model đó, bỏ qua field trong
  event. Bật N worker với N giá trị khác nhau thì **cùng một event được cả N model xử lý**,
  vì khác consumer group. Đây là chế độ shadow-run và là cách `evaluator` chạy benchmark —
  không cần code riêng cho việc so model.

### 3.8 Service tự mô tả qua `/v1/info`

```json
{"name": "ocr", "task": "ocr", "capability_input": "image",
 "capability_output": "text_boxes", "version": "0.1.0",
 "invoke_path": "/v1/ocr", "default_model": "paddleocr-v4-vi"}
```

Dashboard đọc capability từ gateway rồi tự chọn uploader và viewer. Service thứ ba
(NER, TTS...) chỉ cần trả đúng `/v1/info`, không sửa code dashboard.

**Ghi chú lịch sử:** Plan A để manifest trong `services/*/service.yaml`. Cách đó
chỉ đọc được khi đứng cùng máy, mà gateway ở máy khác — nên Plan B1 thay bằng
endpoint HTTP và **xoá hẳn file YAML**. Giữ lại cả hai sẽ thành hai nguồn sự thật,
và cái không ai đọc sẽ lặng lẽ trôi khỏi cái đang chạy: lúc phát hiện thì
`service.yaml` của asr đã ghi `bytes/json` trong khi service thật trả
`audio/transcript`.

## 4. Định dạng dataset có nhãn

Canonical format — mọi importer đều quy về đây, evaluator chỉ đọc format này:

```
datasets/invoice-vi-v2/
├── dataset.yaml
├── items.jsonl
└── media/                # hoặc trỏ s3://
```

```yaml
# dataset.yaml
slug: invoice-vi-v2
task: ocr
media_root: s3://datasets/invoice-vi-v2/media
count: 500
scoring:
  text_normalization:
    unicode_form: NFC
    lowercase: true
    strip_punctuation: true
```

**OCR** — mỗi dòng một item:

```json
{"item_id":"inv_0001","input":"images/inv_0001.jpg",
 "meta":{"source":"phone","lang":"vi"},
 "ground_truth":{
   "full_text":"CÔNG TY ABC\nHÓA ĐƠN BÁN HÀNG",
   "boxes":[
     {"id":0,"polygon":[[120,88],[430,88],[430,132],[120,132]],"text":"CÔNG TY ABC","ignore":false},
     {"id":1,"polygon":[[120,150],[380,146],[382,190],[120,194]],"text":"HÓA ĐƠN BÁN HÀNG","ignore":false},
     {"id":2,"polygon":[[500,300],[560,300],[560,320],[500,320]],"text":"","ignore":true}
   ]}}
```

**ASR:**

```json
{"item_id":"call_0042","input":"audio/call_0042.wav",
 "meta":{"duration_s":37.4,"sample_rate":16000,"domain":"callcenter"},
 "ground_truth":{
   "text":"xin chào anh cho em hỏi về đơn hàng ạ",
   "segments":[
     {"start":0.42,"end":2.15,"text":"xin chào anh","speaker":"A"},
     {"start":2.40,"end":5.10,"text":"cho em hỏi về đơn hàng ạ","speaker":"B"}
   ]}}
```

Bốn quyết định có chủ đích:

- **`polygon` thay vì `bbox`** — chữ trên ảnh chụp tay thường nghiêng hoặc cong. Bbox thẳng
  trục là trường hợp đặc biệt của polygon; ngược lại thì mất thông tin.
- **`ignore: true`** — vùng mờ, không đọc được. Theo quy ước ICDAR, model đoán trúng hay trật
  ở đó đều không tính điểm. Thiếu cờ này thì model tốt bị trừ điểm oan.
- **`full_text` tách khỏi `boxes`** — cho phép chấm 3 chế độ: chỉ detection (IoU/HMean), chỉ
  recognition (CER từng box), hoặc end-to-end (CER trên `full_text`). Dataset chỉ có
  transcript, không có box, vẫn dùng được. `segments` của ASR cũng không bắt buộc.
- **`unicode_form: NFC` nằm trong config** — tiếng Việt có hai cách mã hoá dấu: dựng sẵn
  (`ế` = 1 codepoint) và tổ hợp (`e` + 2 dấu). Hai chuỗi hiển thị giống hệt nhau nhưng khác
  byte. Ground truth lưu NFD mà model trả NFC thì CER ra số vô nghĩa, mắt thường không phát
  hiện được. Phải chuẩn hoá trước khi so.

Importer cắm thêm trong `evaluator/datasets/importers/`: `paddleocr`, `icdar`, `labelstudio`,
`kaldi`, `commonvoice`, `passthrough`. Hai lệnh CLI:

```bash
vypq-eval import --format paddleocr --src ./raw --out datasets/invoice-vi-v2
vypq-eval validate datasets/invoice-vi-v2   # media tồn tại? polygon hợp lệ? encoding NFC?
```

Bộ test có sẵn khớp importer nào thì dùng luôn; không khớp thì viết thêm một adapter,
không đụng lõi.

## 5. Cây thư mục

```
vypq-services/
├── packages/
│   ├── vypq-core/          # create_app, create_worker, config, logging, health,
│   │                       # metrics, errors, storage, http_client (retry+breaker)
│   ├── vypq-events/        # topics, EventEnvelope, producer, consumer (retry/DLQ/pause)
│   ├── vypq-contracts/     # Pydantic schema dùng chung; sinh type TS qua OpenAPI
│   └── vypq-client/        # SDK Python gọi service
│
├── services/               # CPU, stateless
│   ├── _template/
│   ├── ocr/
│   │   ├── service.yaml  config.yaml  Dockerfile
│   │   └── src/ocr_service/
│   │       ├── main.py         # HTTP entrypoint
│   │       ├── worker.py       # Kafka entrypoint
│   │       ├── handler.py      # logic dùng chung
│   │       ├── backend/        # base.py, remote.py, fake.py
│   │       └── pipeline/       # preprocess, postprocess
│   └── asr/
│
├── apps/
│   ├── model-host/         # GPU — deploy riêng lên máy khác
│   │   ├── models.yaml     # NGUỒN SỰ THẬT về model
│   │   └── src/model_host/
│   │       ├── main.py  registry.py  vram.py
│   │       ├── api/routes.py       # /v1/infer /v1/models /health /ready
│   │       └── runners/            # base, paddle, vietocr, whisper, phowhisper
│   ├── gateway/
│   │   └── src/gateway/
│   │       ├── registry/           # service + model registry sync, health poller
│   │       ├── proxy.py            # sync
│   │       ├── dispatcher.py       # async → Kafka
│   │       ├── result_consumer.py  # results → DB → SSE
│   │       ├── history/  api/
│   ├── evaluator/
│   │   └── src/evaluator/
│   │       ├── datasets/           # importers/, loader, validator
│   │       ├── metrics/            # text (CER/WER), detection (IoU/HMean), perf
│   │       ├── runner.py  scoring.py  cli.py  api/
│   └── dashboard/          # Next.js + TS + Tailwind + shadcn
│       ├── app/            # services, hosts, playground/[slug], models,
│       │                   # benchmarks + benchmarks/[evalId], history, metrics
│       └── components/viewers/     # OcrViewer, AsrViewer, DiffViewer
│
├── infra/                  # redpanda, postgres, minio, traefik, prometheus, grafana
├── config/services.yaml
└── scripts/  docs/
```

## 6. Schema dữ liệu (Postgres)

```
services(id, slug, base_url, capability, status, last_seen_at)

model_hosts(id, name, url, token_enc, status, gpu_info_json,
            registered_at, last_seen_at)          -- máy thuê: sinh ra rồi mất

model_versions(id, service_slug, model_id, kind, runner, base_model_id,
               source_uri, host_id, params_json, trained_on_dataset_id, registered_at)
  UNIQUE(service_slug, model_id, host_id)

datasets(id, slug, task, size, storage_uri, scoring_json, created_at)
dataset_items(id, dataset_id, item_id, input_uri, ground_truth_json)
  UNIQUE(dataset_id, item_id)

runs(id, trace_id, service_slug, model_version_id, mode, input_uri,
     output_json, latency_ms, status, error, created_at)
  UNIQUE(trace_id, model_version_id)

eval_jobs(id, dataset_id, model_version_ids[], status,
          total_items, failed_items, started_at, finished_at)
eval_item_results(id, eval_job_id, model_version_id, dataset_item_id,
                  run_id, metrics_json)
eval_results(id, eval_job_id, model_version_id, metrics_json,
             latency_p50, latency_p95, coverage)
```

`eval_item_results` là bảng cho phép trang diff: click một model trong leaderboard và thấy
chính xác những item nó làm sai so với model khác. Thông tin này hữu ích khi fine-tune hơn
nhiều so với một con số CER tổng hợp.

`coverage` trên `eval_results` để không so nhầm model chạy đủ 500 item với model chỉ chạy
được 430 vì lỗi.

**Eval chạy tiếp được.** Máy GPU thuê theo giờ có thể tắt giữa chừng. `runner` bỏ qua mọi
item đã có bản ghi trong `eval_item_results` cho cặp `(model_version_id, dataset_item_id)`,
nên thuê máy mới rồi chạy lại đúng lệnh cũ là nó tiếp từ chỗ dừng. Thay đổi nhỏ về code
nhưng đáng kể về chi phí: không trả tiền GPU để tính lại thứ đã tính.

## 7. Xử lý lỗi

- Service trả error envelope thống nhất; lỗi 5xx không lộ traceback ra ngoài.
- model-host không với tới được → circuit breaker mở → service `/ready` degraded →
  gateway trả 503 rõ ràng; Kafka worker pause thay vì đổ DLQ (mục 3.5).
- Model không load được (thiếu checkpoint, hết VRAM) → model-host vẫn start, model đó
  đánh dấu `unavailable` trong `/v1/models`, không làm sập cả host.
- Worker lỗi thật (input hỏng) → retry backoff → DLQ kèm nguyên nhân và event gốc.
  Dashboard hiện số lượng DLQ theo topic.
- Eval job có item lỗi → vẫn hoàn tất, ghi `failed_items` và `coverage`.

## 8. Chiến lược kiểm thử

- `packages/` — unit test thuần.
- `vypq-events` — test consumer/DLQ/retry/pause với Redpanda trong testcontainer.
- `services/` — test bằng `FakeBackend`, chạy nhanh trong CI **không cần GPU**. Đây là lý do
  chính khiến backend được tách thành interface.
- `services` ↔ `model-host` — test hợp đồng: cùng bộ schema, chạy model-host thật với một
  model nhỏ, đánh dấu `@pytest.mark.slow`.
- `evaluator/metrics` — **viết test trước**. Chuẩn bị cặp (prediction, ground truth) đã biết
  CER/WER tính tay, rồi mới code. Metric sai thì toàn bộ leaderboard vô nghĩa.
  Bao gồm case NFC/NFD để chắc chắn chuẩn hoá hoạt động.
- `dashboard` — test component cho viewer (bbox overlay, diff), Playwright cho luồng chính.
- `scripts/smoke-test.sh` — kiểm tra toàn stack sau `docker compose up`.

## 9. Thứ tự triển khai

Chia thành 4 plan độc lập, mỗi plan xong là dùng được thật.

**Plan A — Nền tảng service** (6 bước) · **B — Gateway & Dashboard** (4) · **C — Benchmark** (3) · **D — Crawler** (1)

**Plan A — Nền tảng service**

| # | Việc | Kiểm chứng |
|---|---|---|
| 1 | `vypq-core`, `vypq-contracts`, `vypq-events` | Publish/consume một event qua Redpanda; DLQ và pause hoạt động |
| 2 | `model-host` + runner `paddle` + auth bearer | Deploy lên máy thuê, mở ngrok, `POST /v1/infer` multipart trả kết quả thô; gọi không token bị 401 |
| 3 | `services/ocr`: RemoteBackend + FakeBackend + HTTP + pre/post | `curl` ảnh → bbox JSON đúng contract; test CI chạy không cần GPU |
| 4 | `services/ocr`: Kafka worker + breaker + pause | Tắt model-host giữa chừng → worker pause, bật lại → chạy tiếp, không mất message |
| 5 | `_template` + `new-service.sh` | Sinh service mới có sẵn hai entrypoint và hai backend |
| 6 | `services/asr` + runner `whisper` | Dựng bằng chính script bước 5 |

Trong Plan A, `host_discovery.source: static` — danh sách host lấy từ `fallback_static` trong
config. Discovery động qua gateway đến ở bước 7. Nhờ vậy Plan A chạy và test được trọn vẹn
mà chưa cần gateway tồn tại; đổi sang động sau chỉ là đổi một dòng config, không sửa code.

**Plan B — Gateway & Dashboard**

| # | Việc | Kiểm chứng |
|---|---|---|
| 7 | `gateway`: host registry + poll + routing, service registry, sync, async, DB | Đăng ký 2 host, tắt 1 → sau 45s tự gỡ khỏi routing, request vẫn chạy qua host còn lại |
| 8 | `services`: chuyển sang `host_discovery.source: gateway` | Thêm host mới lúc service đang chạy → service tự thấy, không restart |
| 9 | `dashboard`: hosts, services, playground, models | Dán URL ngrok vào UI → host lên xanh; upload ảnh → bbox overlay, chọn được model |
| 10 | Prometheus, Grafana, consumer lag | Biểu đồ latency, error, lag từng consumer group |

**Plan C — Benchmark**

| # | Việc | Kiểm chứng |
|---|---|---|
| 11 | `evaluator`: format dataset, importer, `validate` | Import bộ test có sẵn, validate pass |
| 12 | `evaluator`: metrics + runner + scoring + resume | CER/WER đúng kể cả case NFD; giết runner giữa chừng, chạy lại → tiếp từ item dở |
| 13 | `dashboard/benchmarks`: leaderboard + diff | So Paddle vs VietOCR trên dataset thật, xem item sai |

**Plan D — Crawler** (repo `vypq-crawler`)

| # | Việc | Kiểm chứng |
|---|---|---|
| 14 | Skeleton + 1 spider + `crawl.documents.ready` | Crawl → MinIO → OCR chạy tự động qua event |

Làm trọn Plan A trước vì nó định ra contract mà B, C, D đều xây lên. Contract sai thì sửa
ở A rẻ hơn nhiều so với sửa sau khi đã có dashboard.

## 10. Quyết định đã chốt

| Quyết định | Lựa chọn | Lý do |
|---|---|---|
| Tổ chức repo | Monorepo services + repo crawler riêng | Dùng chung contract/SDK; crawler khác lifecycle |
| Hạ tầng | Máy ứng dụng CPU + máy GPU riêng, Docker Compose | Theo hạ tầng sẵn có; service test được không cần GPU |
| Stack | FastAPI + Next.js/TypeScript | Thống nhất hệ sinh thái Python; UI đủ linh hoạt cho overlay/diff |
| Broker | Redpanda | Tương thích Kafka API, nhẹ hơn Kafka thuần |
| Transport | Giữ cả HTTP và Kafka | HTTP cho playground (độ trễ thấp), Kafka cho batch/eval/crawler |
| Nơi load model | `apps/model-host` trên máy GPU | Tách hẳn VRAM khỏi service; service stateless, scale và test dễ |
| Nguồn sự thật về model | `model-host/models.yaml` | Một chỗ duy nhất; thêm checkpoint fine-tune = một khối YAML |
| Truyền dữ liệu giữa 2 máy | multipart inline (mặc định), MinIO URI khi cùng mạng | Máy thuê không với tới MinIO nội bộ; multipart không phình như base64 |
| Danh sách máy GPU | Registry động trong gateway, gateway poll ra | Máy thuê theo giờ, URL đổi liên tục; cả hai đầu đều sau NAT |
| Nhiều GPU | Một container mỗi GPU, đăng ký thành host riêng | Không cần code chia GPU; máy 4 GPU giống hệt 4 máy 1 GPU |
| Kho checkpoint | Object store ngoài (R2), tách khỏi MinIO nội bộ | Máy thuê phải tải lại weights mỗi lần; R2 miễn phí egress |
| Truy cập máy GPU | ngrok + bearer token bắt buộc | Máy thuê không cài được VPN; URL ngrok bị quét tự động |
| Ground truth | Format canonical JSONL + importer cắm thêm | Bộ test có sẵn quy về một định dạng, evaluator chỉ đọc một thứ |

## 11. Vấn đề còn mở

- **Định dạng gốc của bộ test có nhãn hiện có** chưa biết. Xử lý ở bước 10 bằng importer;
  cần một mẫu dữ liệu trước khi làm bước đó. Nếu khớp `paddleocr`/`icdar`/`labelstudio`
  thì dùng luôn, không cần viết thêm.
- **Ngưỡng `vram_budget_mb`** đặt sau khi đo trên máy GPU thật. Không chặn việc triển khai:
  giá trị khởi đầu lấy 80% VRAM khả dụng, chỉnh sau bằng config.
### Ghi nhận từ review tổng Plan A

Những điểm dưới đây đã được cân nhắc và quyết định, ghi lại ở đây để không phải
tranh luận lại — và để Plan B, C không vấp phải.

- **`InferenceFailed` chưa ai publish.** Schema có sẵn, mang `eval_job_id` và
  `dataset_item_id`, nhưng không chỗ nào dựng nó. Evaluator ở Plan C nộp N item
  rồi chờ N sự kiện kết thúc sẽ **treo vĩnh viễn** khi có item hỏng, vì đường
  DLQ chỉ chứa JSON thô. Plan C phải bổ sung: `EventConsumer` nhận thêm callback
  `on_dead_letter`, worker dùng nó để phát `InferenceFailed` sang topic kết quả.
- **Chấm điểm OCR phải tách hai tầng.** `OcrResult.boxes` giữ đủ box đã rescale
  và chuẩn hoá NFC, nên detection (IoU/HMean) và recognition (CER từng box) chấm
  được trực tiếp từ đó. Còn `full_text` đi qua heuristic gom dòng của service —
  chấm CER trên nó là chỉ số **end-to-end**, hợp lệ, nhưng không được dùng để
  kết luận model nào nhận dạng tốt hơn. Model trả box mức từ trên ảnh hơi nghiêng
  sẽ bị trừ điểm vì cách gom dòng chứ không phải vì nhận dạng kém.
- **Benchmark phải ghim `max_side` giống nhau giữa các model được so.**
  `prepare_image` thu nhỏ ảnh xuống `max_side` TRƯỚC khi model nhìn thấy gì. Hai
  lần chạy với `max_side` khác nhau đưa cho model hai bức ảnh khác nhau, nên
  chênh lệch điểm không còn nói lên điều gì về model. Đây là biến gây nhiễu im
  lặng, không có gì trong hệ thống hiện cảnh báo.
- **`full_text` là chỉ số đường ống, không phải chỉ số nhận dạng** — mạnh hơn mức
  đã nêu ở trên: `text_from_lines` còn bỏ hẳn dòng toàn box `ignore` và gộp
  khoảng trắng trong dòng. Chấm nhận dạng thì dùng `boxes`.
- **Bố cục hai cột bị trộn xen kẽ** (đã ghim bằng test). Cần tách cột kiểu XY-cut.
  Ảnh hưởng trực tiếp tới CER trên hoá đơn nhiều cột ở Plan C.
- **`@runtime_checkable` chỉ kiểm method có mặt, không kiểm chữ ký.** Plan B thay
  `StaticHostRegistry` bằng bản discovery sau cùng Protocol này; một bản cài
  `lease()` thành hàm sync vẫn lọt `isinstance`. Thêm kiểm tra conformance bằng
  mypy khi bản đó ra đời.
- **`HostRef.healthy` chưa từng được ghi ở đâu** — nó mới chỉ là hằng số đọc từ
  config. Bản discovery của Plan B là chỗ đầu tiên thực sự cập nhật nó.
- **`default_is_retryable` phân loại theo KIỂU exception, không theo `ErrorCode`.**
  Có một chỗ `ServiceError(ErrorCode.UPSTREAM_ERROR)` cố ý bị dead-letter
  (`_parse` khi model-host trả sai kiểu output — lỗi cấu hình, retry mãi chỉ kẹt
  partition). Ai "dọn dẹp" cho `default_is_retryable` đọc `ErrorCode` sẽ lật
  ngược cả hai và làm hỏng bảo đảm không-mất-dữ-liệu. Đừng làm.
- **Cần metric và alert trên `dlq_publish_failed` + `consumer_paused`** trước khi
  chạy không người trông. DLQ hỏng vĩnh viễn sẽ kẹt cả partition, im lặng.
  Đây là bước 10 trong lộ trình Plan B.

- **Nhà cung cấp GPU thuê** (Vast.ai, Runpod, ...) chưa chốt. Không ảnh hưởng thiết kế: yêu
  cầu duy nhất là chạy được Docker + có Internet ra ngoài. Chọn khi bắt đầu bước 2.
