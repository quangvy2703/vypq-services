# Thiết kế: Nền tảng AI Services (vypq-services)

- **Ngày:** 2026-08-18
- **Trạng thái:** Đã duyệt, chờ lập implementation plan

## 1. Mục tiêu

Dựng một nền tảng để host nhiều mô hình AI (khởi đầu: OCR, ASR) thành các service độc lập,
kèm một trang quản lí trung tâm để test và để **so sánh điểm số giữa model open-source và
model tự fine-tune**. Dữ liệu huấn luyện được thu thập bởi một repo crawler tách biệt.

### Tiêu chí thành công

1. Thêm một model service mới không phải sửa code của gateway hay dashboard.
2. Thêm một model version mới (ví dụ checkpoint fine-tune) không phải rebuild image.
3. So sánh được 2+ model version trên cùng một dataset có nhãn, xem được cả điểm tổng hợp
   lẫn từng item sai.
4. Mỗi service build, chạy, test được độc lập.

### Ngoài phạm vi (YAGNI)

- Kubernetes, auto-scaling, multi-tenant, phân quyền người dùng.
- Training pipeline. Nền tảng này chỉ *phục vụ* và *đánh giá* model, không train.
- Quản lí thử nghiệm kiểu MLflow/W&B.

## 2. Cấu trúc repo

Hai repo, cùng cấp trong `~/WorkingSpace/`:

- `vypq-services/` — monorepo: shared packages, model services, gateway, evaluator, dashboard, infra.
- `vypq-crawler/` — repo riêng: thu thập dữ liệu web.

Tách vì crawler có lifecycle khác hẳn (chạy theo lịch, phụ thuộc browser/proxy, scale theo I/O
chứ không theo GPU). Hai repo nối nhau qua MinIO và Redpanda, không gọi API trực tiếp.

## 3. Kiến trúc

```
Browser ─▶ Dashboard (Next.js) ─▶ Gateway (FastAPI) ─┬─ HTTP sync ──▶ ocr-service
                                    │                 └─ publish ────▶ Redpanda
                                    ├─ Postgres (registry, runs, evals)
                                    └─ MinIO (ảnh, audio, checkpoint)

Evaluator ─publish─▶ infer.*.requests ─▶ worker (mỗi model version = 1 consumer group)
Crawler   ─publish─▶                            │
Gateway   ◀─consume─ infer.*.results  ◀─────────┘        lỗi ─▶ infer.*.dlq
```

### 3.1 Hai transport, một lõi

Mỗi model service có hai entrypoint gọi chung một hàm xử lý:

- `main.py` → FastAPI, dùng cho playground và debug (độ trễ thấp).
- `worker.py` → Kafka consumer, dùng cho batch, evaluation, luồng crawler→OCR.

Cả hai gọi `handler.handle(request) -> response`, hàm này gọi `engine.predict()`.
Lớp `engine/` không biết gì về transport. Thêm transport mới không đụng vào model.

### 3.2 Event bus

Broker: **Redpanda** (tương thích Kafka API, client dùng `aiokafka`). Chọn vì chạy chung
server với model, 1 binary, không cần JVM/ZooKeeper.

Topics:

| Topic | Producer | Consumer |
|---|---|---|
| `infer.ocr.requests` | gateway, evaluator, crawler | ocr workers |
| `infer.ocr.results` | ocr workers | gateway, evaluator |
| `infer.ocr.dlq` | consumer helper | thủ công / dashboard |
| `infer.asr.*` | như trên | như trên |
| `crawl.documents.ready` | crawler | gateway |

- Partition key = `trace_id` → mọi event của một request nằm cùng partition, giữ thứ tự.
- Delivery: at-least-once. Consumer commit offset **sau khi** xử lý xong. Chống trùng bằng
  khoá duy nhất `(trace_id, model_version_id)` trên bảng `runs`.
- Retry có backoff trong `vypq_events.consumer`, quá số lần thì đẩy sang DLQ kèm nguyên nhân.
**Consumer group và chọn model.** Worker chạy với biến môi trường `MODEL_VERSION`:

- **Không đặt** → group `{service}-default`. Worker phục vụ model nào mà event chỉ định
  trong `model_version` (không có thì dùng model `default`). Đây là chế độ thường ngày.
- **Có đặt** → group `{service}-{model_version}`. Worker ép dùng đúng model đó và bỏ qua
  field trong event. Bật N worker với N giá trị khác nhau thì **cùng một event được cả N
  model xử lý**, vì khác consumer group. Đây là chế độ shadow-run phục vụ so sánh, và là
  cách `evaluator` chạy benchmark — không cần code riêng cho việc so model.

### 3.3 Model registry

Mỗi service khai báo `models.yaml`; service load nhiều model cùng lúc, request chọn qua
field `model_version` (không có thì dùng model `default: true`).

```yaml
models:
  - id: paddleocr-v4-vi
    kind: opensource
    engine: paddle
    source: {type: hf, repo: PaddlePaddle/PP-OCRv4}
    default: true
  - id: vietocr-ft-invoice-20260801
    kind: finetuned
    engine: vietocr
    base: vietocr-base
    source: {type: s3, uri: s3://models/ocr/vietocr-ft-invoice-20260801}
    trained_on: invoice-vi-v2
```

- Thêm model fine-tune = thêm một khối YAML + upload checkpoint. Không sửa code, không rebuild.
- `vypq_core.model_registry` lo lazy load + LRU eviction theo ngân sách VRAM cấu hình được.
- Gateway poll `/info` của service, đồng bộ vào bảng `model_versions`. **Service là nguồn sự
  thật**, DB chỉ là bản sao để truy vấn.

### 3.4 Service manifest

`service.yaml` khai báo capability và topic tiêu thụ:

```yaml
name: ocr
port: 8001
capability: {input: image, output: text_boxes}
consumes: [infer.ocr.requests]
produces: [infer.ocr.results]
```

Dashboard đọc capability từ gateway rồi **tự chọn uploader và viewer**. Service thứ ba
(NER, TTS...) chỉ cần khai báo manifest, không sửa code dashboard.

## 4. Các thành phần

### packages/

- `vypq-core` — `create_app()`, `create_worker()`, model registry, config, logging JSON,
  health (`/health` `/ready` `/info`), metrics Prometheus, error envelope, storage adapter.
- `vypq-events` — định nghĩa topic, `EventEnvelope`, producer/consumer có retry + DLQ,
  schema event (`InferenceRequested/Completed/Failed`, `EvalJobRequested`).
- `vypq-contracts` — Pydantic schema dùng chung service ↔ gateway ↔ dashboard.
  Nguồn sinh type TypeScript cho dashboard qua OpenAPI.
- `vypq-client` — SDK Python gọi service, dùng trong test và script batch.

### services/

`_template/` sinh sẵn cả hai entrypoint. `ocr/` (paddle, vietocr) và `asr/` (whisper,
phowhisper). Weights nằm ngoài git, tải bằng `scripts/fetch-models.sh`.

### apps/gateway

Registry service + model, health poller, `proxy.py` (đường sync), `dispatcher.py`
(đường async), `result_consumer.py` (ghi DB, đẩy SSE về dashboard), history.

### apps/evaluator

- `datasets/` — importer đưa dataset có nhãn về định dạng nội bộ JSONL
  (`{item_id, input_uri, ground_truth}`). Định dạng nguồn của người dùng sẽ được xác định
  ở bước 8; importer thiết kế theo dạng cắm thêm để không phải sửa lõi.
- `metrics/` — `text.py` (CER, WER, chuẩn hoá Unicode tiếng Việt), `detection.py`
  (IoU, Precision/Recall/F1, HMean), `perf.py` (latency p50/p95, RTF, throughput).
- `runner.py` — fan-out job theo tích (dataset × model version) lên Kafka.
- `scoring.py` — gom kết quả, tính tổng hợp, ghi DB.

### apps/dashboard

Next.js + TypeScript + Tailwind + shadcn. Trang: `services`, `playground/[slug]`,
`models`, `benchmarks` + `benchmarks/[evalId]` (diff từng item), `history`, `metrics`.

### infra/

Redpanda + console, Postgres + alembic, MinIO, Traefik, Prometheus, Grafana.

## 5. Schema dữ liệu (Postgres)

```
services(id, slug, base_url, capability, status, last_seen_at)

model_versions(id, service_slug, model_id, kind, engine, base_model_id,
               source_uri, params_json, trained_on_dataset_id, registered_at)
  UNIQUE(service_slug, model_id)

datasets(id, slug, task, size, storage_uri, created_at)
dataset_items(id, dataset_id, input_uri, ground_truth_json)

runs(id, trace_id, service_slug, model_version_id, mode, input_uri,
     output_json, latency_ms, status, error, created_at)
  UNIQUE(trace_id, model_version_id)          -- chống xử lý trùng

eval_jobs(id, dataset_id, model_version_ids[], status, started_at, finished_at)
eval_item_results(id, eval_job_id, model_version_id, dataset_item_id,
                  run_id, metrics_json)
eval_results(id, eval_job_id, model_version_id, metrics_json,
             latency_p50, latency_p95)
```

`eval_item_results` là bảng cho phép trang diff: click một model trong leaderboard và thấy
chính xác những item nó làm sai so với model khác. Đây là thông tin hữu ích khi fine-tune,
hơn một con số CER tổng hợp.

## 6. Xử lý lỗi

- Model service trả error envelope thống nhất; lỗi 5xx không bao giờ lộ traceback ra ngoài.
- Worker lỗi → retry có backoff → DLQ kèm nguyên nhân và event gốc. Dashboard hiện số
  lượng DLQ theo topic.
- Service chết → health poller đánh dấu offline, dashboard hiện trạng thái, gateway trả
  503 rõ ràng thay vì treo.
- Eval job có item lỗi → vẫn hoàn tất, ghi nhận `failed_items`; leaderboard hiện tỉ lệ phủ
  để không so nhầm model chạy đủ với model chạy thiếu.
- Model không load được (thiếu checkpoint, hết VRAM) → service vẫn start, `/ready` báo
  degraded, model đó bị đánh dấu unavailable thay vì làm sập cả service.

## 7. Chiến lược kiểm thử

- `packages/` — unit test thuần, không cần model.
- `vypq-events` — test consumer/DLQ/retry với Redpanda chạy trong testcontainer.
- `services/` — test API bằng engine giả (fake engine) để chạy nhanh trong CI; thêm một
  test tích hợp có model thật, đánh dấu `@pytest.mark.slow`.
- `evaluator/metrics` — **viết test trước**. Chuẩn bị cặp (prediction, ground truth) đã
  biết CER/WER tính tay, rồi mới code. Metric sai thì toàn bộ leaderboard vô nghĩa.
- `dashboard` — test component cho viewer (bbox overlay, diff), Playwright cho luồng chính.
- `scripts/smoke-test.sh` — kiểm tra toàn stack sau khi `docker compose up`.

## 8. Thứ tự triển khai

| # | Việc | Kiểm chứng |
|---|---|---|
| 1 | `vypq-core`, `vypq-contracts`, `vypq-events` | Publish/consume một event qua Redpanda, DLQ hoạt động |
| 2 | `services/ocr`: engine + HTTP + models.yaml | `curl` ảnh → bbox JSON; đổi `model_version` ra kết quả khác |
| 3 | `services/ocr`: Kafka worker | Cùng ảnh gửi qua topic, nhận result event |
| 4 | `_template` + `new-service.sh` | Sinh service mới có sẵn hai entrypoint |
| 5 | `services/asr` | Dựng bằng chính script bước 4 |
| 6 | `gateway`: registry, sync, async, DB | `/services`, `/models`, `/invoke` cả hai mode |
| 7 | `dashboard`: services, playground, models | Upload ảnh trên UI → bbox overlay, chọn được model |
| 8 | `evaluator`: dataset importer, metrics, runner | CER/WER đúng trên input đã biết đáp án |
| 9 | `dashboard/benchmarks`: leaderboard + diff | So Paddle vs VietOCR trên dataset thật, xem item sai |
| 10 | Prometheus, Grafana, consumer lag | Biểu đồ latency, error, lag từng consumer group |
| 11 | `vypq-crawler` + 1 spider + `crawl.documents.ready` | Crawl → MinIO → OCR chạy tự động qua event |

## 9. Quyết định đã chốt

| Quyết định | Lựa chọn | Lý do |
|---|---|---|
| Tổ chức repo | Monorepo services + repo crawler riêng | Dùng chung contract/SDK; crawler khác lifecycle |
| Hạ tầng | 1 server GPU + Docker Compose | Đủ cho giai đoạn này; Dockerfile chuẩn nên chuyển k8s sau vẫn dễ |
| Stack | FastAPI + Next.js/TypeScript | Thống nhất hệ sinh thái Python cho model; UI đủ linh hoạt cho overlay/diff |
| Broker | Redpanda | Tương thích Kafka API, nhẹ hơn nhiều trên server dùng chung với GPU |
| Transport | Giữ cả HTTP và Kafka | HTTP cho playground (độ trễ thấp), Kafka cho batch/eval/crawler |
| Chọn model | Registry đa model trong service | Đổi model bằng tham số request → so sánh được; không rebuild khi thêm checkpoint |
| Ground truth | Dùng bộ test có nhãn sẵn của người dùng | Không cần dựng luồng gán nhãn ở giai đoạn này |

## 10. Vấn đề còn mở

- **Định dạng dataset có nhãn hiện có** chưa biết. Xử lý ở bước 8 bằng importer cắm thêm;
  cần một mẫu dữ liệu trước khi làm bước đó.
- **Ngân sách VRAM** khi bật nhiều model version cùng lúc. Giải quyết bằng lazy load + LRU;
  ngưỡng cụ thể đặt sau khi đo trên phần cứng thật.
