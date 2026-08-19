import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GatewayError } from "@/lib/errors";

vi.mock("@/lib/gateway", () => ({
  gateway: {
    listHosts: vi.fn(),
    registerHost: vi.fn(),
    deleteHost: vi.fn(),
    listServices: vi.fn(),
  },
}));

const { gateway } = await import("@/lib/gateway");
const { GET, POST } = await import("@/app/api/hosts/route");
const { DELETE } = await import("@/app/api/hosts/[name]/route");
const { GET: getServices } = await import("@/app/api/services/route");

// Không dùng Record<string, ...> ở đây: với noUncheckedIndexedAccess, truy cập
// qua index signature luôn trả về `X | undefined`, buộc phải non-null-assert
// khắp nơi bên dưới. Khai rõ từng field giữ đúng kiểu ReturnType<typeof vi.fn>
// mà không đổi giá trị mock nào so với brief.
interface MockedGateway {
  listHosts: ReturnType<typeof vi.fn>;
  registerHost: ReturnType<typeof vi.fn>;
  deleteHost: ReturnType<typeof vi.fn>;
  listServices: ReturnType<typeof vi.fn>;
}

const mocked = gateway as unknown as MockedGateway;

function jsonRequest(body: unknown): Request {
  return new Request("http://localhost:3001/api/hosts", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GET /api/hosts", () => {
  it("chuyển tiếp danh sách host", async () => {
    mocked.listHosts.mockResolvedValue({ hosts: [{ name: "a100" }] });
    const response = await GET();
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ hosts: [{ name: "a100" }] });
  });

  it("giữ nguyên mã lỗi gateway trả về", async () => {
    mocked.listHosts.mockRejectedValue(new GatewayError(503, "upstream_error", "gateway chết", "t1"));
    const response = await GET();
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      code: "upstream_error", message: "gateway chết", trace_id: "t1",
    });
  });

  it("không lộ chi tiết nội bộ khi lỗi không phải từ gateway", async () => {
    // Gateway tắt hẳn → fetch ném TypeError kèm stack và URL nội bộ. Trả nguyên
    // cái đó ra trình duyệt là rò rỉ topology.
    mocked.listHosts.mockRejectedValue(new TypeError("fetch failed: ECONNREFUSED 10.0.0.5:8080"));
    const response = await GET();
    expect(response.status).toBe(502);
    const body = (await response.json()) as { message: string };
    expect(body.message).toBe("không gọi được gateway");
    expect(JSON.stringify(body)).not.toContain("10.0.0.5");
  });
});

describe("POST /api/hosts", () => {
  it("đăng ký host hợp lệ và trả 201", async () => {
    mocked.registerHost.mockResolvedValue({ name: "a100", url: "https://x.ngrok.app" });
    const response = await POST(jsonRequest({ name: "a100", url: "https://x.ngrok.app", token: "bi-mat" }));
    expect(response.status).toBe(201);
    expect(mocked.registerHost).toHaveBeenCalledWith({
      name: "a100", url: "https://x.ngrok.app", token: "bi-mat",
    });
  });

  it("biến token rỗng thành null thay vì gửi chuỗi rỗng", async () => {
    // Gateway phân biệt "host không cần token" (null) với "token là chuỗi rỗng".
    mocked.registerHost.mockResolvedValue({ name: "a100", url: "https://x.ngrok.app" });
    await POST(jsonRequest({ name: "a100", url: "https://x.ngrok.app", token: "  " }));
    expect(mocked.registerHost).toHaveBeenCalledWith({
      name: "a100", url: "https://x.ngrok.app", token: null,
    });
  });

  it.each([
    [{ url: "https://x.ngrok.app" }, "thiếu name"],
    [{ name: "a100" }, "thiếu url"],
    [{ name: "  ", url: "https://x.ngrok.app" }, "name chỉ có khoảng trắng"],
  ])("từ chối %j (%s) với 422", async (body, _description) => {
    const response = await POST(jsonRequest(body));
    expect(response.status).toBe(422);
    expect(mocked.registerHost).not.toHaveBeenCalled();
  });

  it.each(["file:///etc/passwd", "ftp://x", "khong-phai-url", "javascript:alert(1)"])(
    "từ chối URL %s vì poller chỉ gọi được http/https",
    async (url) => {
      const response = await POST(jsonRequest({ name: "a100", url }));
      expect(response.status).toBe(422);
      expect(mocked.registerHost).not.toHaveBeenCalled();
    },
  );

  it("trả 422 khi thân request không phải JSON hợp lệ", async () => {
    const request = new Request("http://localhost:3001/api/hosts", {
      method: "POST", headers: { "content-type": "application/json" }, body: "{",
    });
    const response = await POST(request);
    expect(response.status).toBe(422);
  });
});

describe("DELETE /api/hosts/[name]", () => {
  it("xoá host và trả 200 dù gateway trả 204 rỗng", async () => {
    mocked.deleteHost.mockResolvedValue(undefined);
    const response = await DELETE(new Request("http://localhost:3001/api/hosts/a100", { method: "DELETE" }), {
      params: Promise.resolve({ name: "a100" }),
    });
    expect(response.status).toBe(200);
    expect(mocked.deleteHost).toHaveBeenCalledWith("a100");
  });

  it("chuyển 404 của gateway ra nguyên vẹn", async () => {
    mocked.deleteHost.mockRejectedValue(new GatewayError(404, "bad_input", "không có host tên 'x'", null));
    const response = await DELETE(new Request("http://localhost:3001/api/hosts/x", { method: "DELETE" }), {
      params: Promise.resolve({ name: "x" }),
    });
    expect(response.status).toBe(404);
  });
});

describe("GET /api/services", () => {
  it("chuyển tiếp danh sách service", async () => {
    mocked.listServices.mockResolvedValue({ services: [] });
    const response = await getServices();
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ services: [] });
  });
});
