// Gateway giả cho e2e: đủ 5 endpoint dashboard dùng, giữ trạng thái trong RAM.
// KIỂM TOKEN thật sự — nếu dashboard quên gắn bearer, e2e phải đỏ.
import { createServer } from "node:http";

const TOKEN = process.env.FAKE_GATEWAY_TOKEN ?? "token-e2e";
const PORT = Number(process.env.FAKE_GATEWAY_PORT ?? 8099);

const hosts = new Map();
const runs = [];

const OCR_RESULT = {
  full_text: "HOÁ ĐƠN\nTổng cộng 120000",
  boxes: [
    { id: 1, polygon: [[40, 30], [300, 30], [300, 80], [40, 80]], text: "HOÁ ĐƠN", confidence: 0.98, ignore: false },
    { id: 2, polygon: [[40, 120], [420, 120], [420, 170], [40, 170]], text: "Tổng cộng 120000", confidence: 0.86, ignore: false },
  ],
};

const SERVICES = [
  {
    info: {
      name: "ocr", task: "ocr", capability_input: "image", capability_output: "text_boxes",
      version: "0.1.0", invoke_path: "/v1/ocr", default_model: "paddleocr-v4-vi",
    },
    base_url: "http://ocr:8000", status: "ok", last_seen_at: new Date().toISOString(),
  },
  { info: null, base_url: "http://ner:8000", status: "down", last_seen_at: null },
];

function send(res, status, body) {
  const payload = body === undefined ? "" : JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json" });
  res.end(payload);
}

createServer((req, res) => {
  if (req.headers.authorization !== `Bearer ${TOKEN}`) {
    return send(res, 401, { code: "bad_input", message: "token không hợp lệ", trace_id: null });
  }
  const url = new URL(req.url ?? "/", "http://fake");
  const { pathname } = url;

  if (req.method === "GET" && pathname === "/v1/hosts") {
    return send(res, 200, { hosts: [...hosts.values()] });
  }

  if (req.method === "POST" && pathname === "/v1/hosts") {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk; });
    return req.on("end", () => {
      const body = JSON.parse(raw);
      const state = {
        name: body.name, url: body.url, healthy: true,
        last_seen_at: new Date().toISOString(), last_error: null,
        models: [
          { id: "paddleocr-v4-vi", task: "ocr", kind: "opensource", runner: "paddle", loaded: true, available: true, vram_mb: 1200, base: null, trained_on: null },
          { id: "vietocr-ft-invoice", task: "ocr", kind: "finetuned", runner: "vietocr", loaded: false, available: true, vram_mb: 0, base: "vietocr-base", trained_on: "invoice-vi-v2" },
        ],
      };
      hosts.set(body.name, state);
      send(res, 201, state);
    });
  }

  if (req.method === "DELETE" && pathname.startsWith("/v1/hosts/")) {
    const name = decodeURIComponent(pathname.slice("/v1/hosts/".length));
    if (!hosts.delete(name)) return send(res, 404, { code: "bad_input", message: `không có host tên '${name}'`, trace_id: null });
    res.writeHead(204);
    return res.end();
  }

  if (req.method === "GET" && pathname === "/v1/services") return send(res, 200, { services: SERVICES });

  if (req.method === "POST" && pathname === "/v1/invoke/upload") {
    // Không parse multipart: e2e chỉ cần biết request tới được đây kèm token.
    req.resume();
    return req.on("end", () => {
      const id = `r${runs.length + 1}`;
      const record = {
        id, trace_id: `t${runs.length + 1}`, service: "ocr", model_version: "paddleocr-v4-vi",
        mode: "sync", status: "ok", input_uri: null, output: OCR_RESULT,
        latency_ms: 320, error: null, created_at: new Date().toISOString(),
      };
      runs.unshift(record);
      send(res, 200, { trace_id: record.trace_id, mode: "sync", run_id: id, result: OCR_RESULT });
    });
  }

  if (req.method === "GET" && pathname.startsWith("/v1/runs/")) {
    const id = decodeURIComponent(pathname.slice("/v1/runs/".length));
    const found = runs.find((run) => run.id === id);
    return found ? send(res, 200, found) : send(res, 404, { code: "bad_input", message: "không có run", trace_id: null });
  }

  if (req.method === "GET" && pathname === "/v1/runs") {
    const service = url.searchParams.get("service");
    const filtered = service ? runs.filter((run) => run.service === service) : runs;
    return send(res, 200, { runs: filtered, total: filtered.length });
  }

  send(res, 404, { code: "bad_input", message: `không có route ${pathname}`, trace_id: null });
}).listen(PORT, () => {
  console.log(`fake gateway nghe ở http://127.0.0.1:${PORT}`);
});
