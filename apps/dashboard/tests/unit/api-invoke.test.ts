// @vitest-environment node
//
// File này POST multipart/FormData thẳng vào Route Handler qua `new
// Request(...)`. Dưới môi trường jsdom (mặc định của repo, cho test React),
// `FormData`/`File` là lớp của jsdom còn `Request.formData()` bên trong lại
// dùng undici của Node — hai lớp FormData khác định danh (instanceof) nên
// undici không nhận ra body là multipart và ném lỗi content-type. Ép file
// test này chạy ở môi trường "node" để `FormData`, `File`, `Request` cùng một
// triển khai, không đổi bất kỳ assertion nào so với brief.
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GatewayError } from "@/lib/errors";

vi.mock("@/lib/gateway", () => ({
  gateway: { invokeUpload: vi.fn(), invokeUri: vi.fn(), listRuns: vi.fn(), getRun: vi.fn() },
}));

const { gateway } = await import("@/lib/gateway");
const { POST } = await import("@/app/api/invoke/route");
const { GET: getRuns } = await import("@/app/api/runs/route");
const { GET: getRun } = await import("@/app/api/runs/[runId]/route");

// Không dùng Record<string, ...> ở đây: với noUncheckedIndexedAccess, truy cập
// qua index signature luôn trả về `X | undefined` và tsc chặn ở `pnpm lint`.
// Cùng cách xử lý với MockedGateway trong tests/unit/api-hosts.test.ts, không
// đổi giá trị mock nào so với brief.
interface MockedGateway {
  invokeUpload: ReturnType<typeof vi.fn>;
  invokeUri: ReturnType<typeof vi.fn>;
  listRuns: ReturnType<typeof vi.fn>;
  getRun: ReturnType<typeof vi.fn>;
}

const mocked = gateway as unknown as MockedGateway;

function upload(fields: Record<string, string>, file?: File): Request {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.set(key, value);
  if (file) form.set("file", file, file.name);
  return new Request("http://localhost:3001/api/invoke", { method: "POST", body: form });
}

function smallFile(bytes = 8): File {
  return new File([new Uint8Array(bytes)], "hoadon.png", { type: "image/png" });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("GATEWAY_TOKEN", "token-gateway");
  vi.stubEnv("DASHBOARD_PASSWORD", "matkhau");
  vi.stubEnv("SESSION_SECRET", "bi-mat-phien");
});

describe("POST /api/invoke", () => {
  it("chuyển tiếp file và model_version xuống gateway", async () => {
    mocked.invokeUpload.mockResolvedValue({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} });
    const file = smallFile();
    const response = await POST(upload({ service: "ocr", model_version: "paddleocr-v4-vi" }, file));
    expect(response.status).toBe(200);
    expect(mocked.invokeUpload).toHaveBeenCalledWith("ocr", expect.any(File), "paddleocr-v4-vi");
  });

  it("truyền null khi không chọn model, để service dùng default_model", async () => {
    mocked.invokeUpload.mockResolvedValue({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} });
    await POST(upload({ service: "ocr", model_version: "" }, smallFile()));
    expect(mocked.invokeUpload).toHaveBeenCalledWith("ocr", expect.any(File), null);
  });

  it("từ chối khi thiếu service", async () => {
    const response = await POST(upload({}, smallFile()));
    expect(response.status).toBe(422);
    expect(mocked.invokeUpload).not.toHaveBeenCalled();
  });

  it("từ chối khi không đính kèm file", async () => {
    const response = await POST(upload({ service: "ocr" }));
    expect(response.status).toBe(422);
    expect(mocked.invokeUpload).not.toHaveBeenCalled();
  });

  it("chặn file quá 25 MB TRƯỚC khi gửi lên gateway", async () => {
    // Đẩy 200 MB qua gateway rồi để service từ chối là tốn băng thông và thời
    // gian của cả hai máy; chặn ở đây rẻ hơn và báo lỗi rõ hơn.
    const big = new File([new Uint8Array(25 * 1024 * 1024 + 1)], "to.wav", { type: "audio/wav" });
    const response = await POST(upload({ service: "asr" }, big));
    expect(response.status).toBe(413);
    expect(mocked.invokeUpload).not.toHaveBeenCalled();
    const body = (await response.json()) as { message: string };
    expect(body.message).toMatch(/25 MB/);
  });

  it("chặn theo Content-Length trước khi parse form", async () => {
    // request.formData() của Next ném lỗi trên body quá lớn, và lỗi đó rơi vào
    // nhánh 502 chung "không gọi được gateway" — nói sai hoàn toàn chỗ hỏng.
    // Đọc Content-Length trước thì người dùng nhận đúng 413.
    const request = new Request("http://localhost:3001/api/invoke", {
      method: "POST",
      headers: { "content-length": String(200 * 1024 * 1024) },
      body: new FormData(),
    });
    const response = await POST(request);
    expect(response.status).toBe(413);
    await expect(response.json()).resolves.toMatchObject({ message: expect.stringMatching(/25 MB/) });
    expect(mocked.invokeUpload).not.toHaveBeenCalled();
  });

  it("không chặn nhầm khi Content-Length thiếu hoặc không phải số", async () => {
    mocked.invokeUpload.mockResolvedValue({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} });
    const response = await POST(upload({ service: "ocr" }, smallFile()));
    expect(response.status).toBe(200);
  });

  it("nhận file đúng bằng 25 MB", async () => {
    mocked.invokeUpload.mockResolvedValue({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} });
    const exact = new File([new Uint8Array(25 * 1024 * 1024)], "vua-du.wav", { type: "audio/wav" });
    const response = await POST(upload({ service: "asr" }, exact));
    expect(response.status).toBe(200);
  });

  it("giữ nguyên 502 khi service lỗi thật", async () => {
    mocked.invokeUpload.mockRejectedValue(new GatewayError(502, "upstream_error", "service trả 500", "t9"));
    const response = await POST(upload({ service: "ocr" }, smallFile()));
    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toMatchObject({ code: "upstream_error", trace_id: "t9" });
  });
});

describe("GET /api/runs", () => {
  it("chuyển tiếp bộ lọc từ query string", async () => {
    mocked.listRuns.mockResolvedValue({ runs: [], total: 0 });
    await getRuns(new Request("http://localhost:3001/api/runs?service=ocr&status=failed&trace_id=t1&limit=10&offset=20"));
    expect(mocked.listRuns).toHaveBeenCalledWith({
      service: "ocr", status: "failed", trace_id: "t1", limit: 10, offset: 20,
    });
  });

  it("bỏ qua tham số rỗng thay vì gửi chuỗi rỗng xuống gateway", async () => {
    mocked.listRuns.mockResolvedValue({ runs: [], total: 0 });
    await getRuns(new Request("http://localhost:3001/api/runs?service=&status="));
    expect(mocked.listRuns).toHaveBeenCalledWith({ limit: 50, offset: 0 });
  });

  it("bỏ qua status không hợp lệ thay vì để gateway trả 422", async () => {
    mocked.listRuns.mockResolvedValue({ runs: [], total: 0 });
    await getRuns(new Request("http://localhost:3001/api/runs?status=khong-ton-tai"));
    expect(mocked.listRuns).toHaveBeenCalledWith({ limit: 50, offset: 0 });
  });

  it.each([
    ["limit=0", 1],
    ["limit=9999", 200],
    ["limit=abc", 50],
  ])("kẹp %s vào khoảng gateway chấp nhận", async (query, expected) => {
    mocked.listRuns.mockResolvedValue({ runs: [], total: 0 });
    await getRuns(new Request(`http://localhost:3001/api/runs?${query}`));
    expect(mocked.listRuns).toHaveBeenCalledWith(expect.objectContaining({ limit: expected }));
  });

  it("không cho offset âm", async () => {
    mocked.listRuns.mockResolvedValue({ runs: [], total: 0 });
    await getRuns(new Request("http://localhost:3001/api/runs?offset=-5"));
    expect(mocked.listRuns).toHaveBeenCalledWith(expect.objectContaining({ offset: 0 }));
  });
});

describe("GET /api/runs/[runId]", () => {
  it("trả run theo id", async () => {
    mocked.getRun.mockResolvedValue({ id: "r1" });
    const response = await getRun(new Request("http://localhost:3001/api/runs/r1"), {
      params: Promise.resolve({ runId: "r1" }),
    });
    expect(response.status).toBe(200);
    expect(mocked.getRun).toHaveBeenCalledWith("r1");
  });

  it("chuyển 404 ra nguyên vẹn", async () => {
    mocked.getRun.mockRejectedValue(new GatewayError(404, "bad_input", "không có run 'x'", null));
    const response = await getRun(new Request("http://localhost:3001/api/runs/x"), {
      params: Promise.resolve({ runId: "x" }),
    });
    expect(response.status).toBe(404);
  });
});

describe("POST /api/invoke với input_uri", () => {
  function uriRequest(fields: Record<string, string>): Request {
    const form = new FormData();
    for (const [key, value] of Object.entries(fields)) form.set(key, value);
    return new Request("http://localhost:3001/api/invoke", { method: "POST", body: form });
  }

  it("chuyển tiếp URL xuống gateway thay vì đòi file", async () => {
    mocked.invokeUri.mockResolvedValue({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} });
    const response = await POST(
      uriRequest({ service: "ocr", input_uri: "https://kho/anh.png", model_version: "m1" }),
    );
    expect(response.status).toBe(200);
    expect(mocked.invokeUri).toHaveBeenCalledWith("ocr", "https://kho/anh.png", "m1");
    expect(mocked.invokeUpload).not.toHaveBeenCalled();
  });

  it("từ chối khi vừa có file vừa có URL", async () => {
    // Hai nguồn input trong một request là mơ hồ: chọn bừa một cái nghĩa là
    // người dùng thấy kết quả của thứ mình KHÔNG chọn mà không hề biết.
    const form = new FormData();
    form.set("service", "ocr");
    form.set("input_uri", "https://kho/anh.png");
    form.set("file", smallFile(), "hoadon.png");
    const response = await POST(
      new Request("http://localhost:3001/api/invoke", { method: "POST", body: form }),
    );
    expect(response.status).toBe(422);
    expect(mocked.invokeUri).not.toHaveBeenCalled();
    expect(mocked.invokeUpload).not.toHaveBeenCalled();
  });

  it("từ chối scheme không phải http(s)", async () => {
    // Dashboard là cửa công khai; chặn ở đây cho ra thông báo đúng chỗ hỏng,
    // thay vì để nó thành một lỗi 422 khó hiểu vọng về từ gateway.
    const response = await POST(uriRequest({ service: "ocr", input_uri: "file:///etc/passwd" }));
    expect(response.status).toBe(422);
    expect(mocked.invokeUri).not.toHaveBeenCalled();
  });

  it("vẫn đòi phải có một trong hai", async () => {
    const response = await POST(uriRequest({ service: "ocr" }));
    expect(response.status).toBe(422);
  });
});
