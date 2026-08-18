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

`services/ocr/config.yaml` chỉ khai báo host, không khai báo model (model do host tự công bố):

```yaml
model_hosts:
  - name: gpu-box-1
    url: http://gpu-box:9001
    timeout_s: 30
default_model: paddleocr-v4-vi
```

Service poll `GET /v1/models` của từng host và **lọc theo `task` khớp với capability của
mình** — `services/ocr` chỉ nhận model có `task: ocr`. Nhờ vậy một model-host phục vụ được
nhiều service mà không cần cấu hình chéo.

Phần pre/post-processing (deskew, resize, gộp box, sắp thứ tự đọc, chuẩn hoá Unicode) nằm
trong service — có test, có version. Đây là phần quyết định chất lượng OCR không kém model.

### 3.4 Chịu lỗi khi model-host ở máy khác

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

### 3.5 Hai transport, một lõi

Mỗi service có hai entrypoint gọi chung một hàm xử lý:

- `main.py` → FastAPI, cho playground và debug (độ trễ thấp).
- `worker.py` → Kafka consumer, cho batch, evaluation, luồng crawler→OCR.

Cả hai gọi `handler.handle(request) -> response`. Thêm transport mới không đụng vào backend.

### 3.6 Event bus

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

### 3.7 Service manifest

```yaml
# services/ocr/service.yaml
name: ocr
port: 8001
capability: {input: image, output: text_boxes}
consumes: [infer.ocr.requests]
produces: [infer.ocr.results]
```

Dashboard đọc capability từ gateway rồi tự chọn uploader và viewer. Service thứ ba
(NER, TTS...) chỉ cần khai báo manifest, không sửa code dashboard.

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
│       ├── app/            # services, playground/[slug], models,
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

model_versions(id, service_slug, model_id, kind, runner, base_model_id,
               source_uri, host_name, params_json, trained_on_dataset_id, registered_at)
  UNIQUE(service_slug, model_id)

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

## 7. Xử lý lỗi

- Service trả error envelope thống nhất; lỗi 5xx không lộ traceback ra ngoài.
- model-host không với tới được → circuit breaker mở → service `/ready` degraded →
  gateway trả 503 rõ ràng; Kafka worker pause thay vì đổ DLQ (mục 3.4).
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

**Plan A — Nền tảng service**

| # | Việc | Kiểm chứng |
|---|---|---|
| 1 | `vypq-core`, `vypq-contracts`, `vypq-events` | Publish/consume một event qua Redpanda; DLQ và pause hoạt động |
| 2 | `model-host` + runner `paddle` | Deploy lên máy GPU, `POST /v1/infer` với URI MinIO trả kết quả thô |
| 3 | `services/ocr`: RemoteBackend + FakeBackend + HTTP + pre/post | `curl` ảnh → bbox JSON đúng contract; test CI chạy không cần GPU |
| 4 | `services/ocr`: Kafka worker + breaker + pause | Tắt model-host giữa chừng → worker pause, bật lại → chạy tiếp, không mất message |
| 5 | `_template` + `new-service.sh` | Sinh service mới có sẵn hai entrypoint và hai backend |
| 6 | `services/asr` + runner `whisper` | Dựng bằng chính script bước 5 |

**Plan B — Gateway & Dashboard**

| # | Việc | Kiểm chứng |
|---|---|---|
| 7 | `gateway`: registry, sync, async, DB | `/services`, `/models`, `/invoke` cả hai mode |
| 8 | `dashboard`: services, playground, models | Upload ảnh trên UI → bbox overlay, chọn được model |
| 9 | Prometheus, Grafana, consumer lag | Biểu đồ latency, error, lag từng consumer group |

**Plan C — Benchmark**

| # | Việc | Kiểm chứng |
|---|---|---|
| 10 | `evaluator`: format dataset, importer, `validate` | Import bộ test có sẵn, validate pass |
| 11 | `evaluator`: metrics + runner + scoring | CER/WER đúng trên input đã biết đáp án, kể cả case NFD |
| 12 | `dashboard/benchmarks`: leaderboard + diff | So Paddle vs VietOCR trên dataset thật, xem item sai |

**Plan D — Crawler** (repo `vypq-crawler`)

| # | Việc | Kiểm chứng |
|---|---|---|
| 13 | Skeleton + 1 spider + `crawl.documents.ready` | Crawl → MinIO → OCR chạy tự động qua event |

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
| Truyền dữ liệu giữa 2 máy | MinIO URI | Base64 phình 33%, rất tệ với audio dài |
| Ground truth | Format canonical JSONL + importer cắm thêm | Bộ test có sẵn quy về một định dạng, evaluator chỉ đọc một thứ |

## 11. Vấn đề còn mở

- **Định dạng gốc của bộ test có nhãn hiện có** chưa biết. Xử lý ở bước 10 bằng importer;
  cần một mẫu dữ liệu trước khi làm bước đó. Nếu khớp `paddleocr`/`icdar`/`labelstudio`
  thì dùng luôn, không cần viết thêm.
- **Ngưỡng `vram_budget_mb`** đặt sau khi đo trên máy GPU thật. Không chặn việc triển khai:
  giá trị khởi đầu lấy 80% VRAM khả dụng, chỉnh sau bằng config.
