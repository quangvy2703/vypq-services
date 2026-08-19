import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GatewayError } from "@/lib/errors";
import { gateway } from "@/lib/gateway";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubEnv("GATEWAY_URL", "http://gateway:8080");
  vi.stubEnv("GATEWAY_TOKEN", "token-gateway");
  vi.stubEnv("DASHBOARD_PASSWORD", "matkhau");
  vi.stubEnv("SESSION_SECRET", "bi-mat-phien");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function lastCall(): [string, RequestInit] {
  const call = fetchMock.mock.calls.at(-1);
  if (!call) throw new Error("fetch chưa được gọi");
  return [String(call[0]), (call[1] ?? {}) as RequestInit];
}

describe("gateway.listHosts", () => {
  it("gắn bearer token và gọi đúng /v1/hosts", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ hosts: [] }));
    await gateway.listHosts();
    const [url, init] = lastCall();
    expect(url).toBe("http://gateway:8080/v1/hosts");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer token-gateway");
  });

  it("không bao giờ cache — host thuê theo giờ đổi trạng thái liên tục", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ hosts: [] }));
    await gateway.listHosts();
    expect(lastCall()[1].cache).toBe("no-store");
  });
});

describe("gateway.registerHost", () => {
  it("POST kèm thân JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ name: "a100", url: "https://x.ngrok.app" }, 201));
    await gateway.registerHost({ name: "a100", url: "https://x.ngrok.app", token: "bi-mat" });
    const [url, init] = lastCall();
    expect(url).toBe("http://gateway:8080/v1/hosts");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      name: "a100",
      url: "https://x.ngrok.app",
      token: "bi-mat",
    });
  });
});

describe("gateway.deleteHost", () => {
  it("chịu được 204 không có thân", async () => {
    // Response 204 mà gọi .json() sẽ ném "Unexpected end of JSON input";
    // triệu chứng là xoá host thành công nhưng UI báo lỗi.
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(gateway.deleteHost("a100")).resolves.toBeUndefined();
    expect(lastCall()[1].method).toBe("DELETE");
  });

  it("mã hoá tên host trong đường dẫn", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await gateway.deleteHost("máy a/100");
    expect(lastCall()[0]).toBe("http://gateway:8080/v1/hosts/m%C3%A1y%20a%2F100");
  });
});

describe("gateway.listRuns", () => {
  it("chỉ đưa vào query những tham số thật sự có", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ runs: [], total: 0 }));
    await gateway.listRuns({ service: "ocr", limit: 20, offset: 40 });
    expect(lastCall()[0]).toBe("http://gateway:8080/v1/runs?service=ocr&limit=20&offset=40");
  });

  it("không gửi query rỗng khi không lọc gì", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ runs: [], total: 0 }));
    await gateway.listRuns({});
    expect(lastCall()[0]).toBe("http://gateway:8080/v1/runs");
  });
});

describe("gateway.invokeUpload", () => {
  it("gửi multipart với đúng tên field gateway đang chờ", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} }));
    const file = new File([new Uint8Array([1, 2, 3])], "hoadon.png", { type: "image/png" });
    await gateway.invokeUpload("ocr", file, "paddleocr-v4-vi");
    const body = lastCall()[1].body as FormData;
    expect(body.get("service")).toBe("ocr");
    expect(body.get("model_version")).toBe("paddleocr-v4-vi");
    expect((body.get("file") as File).name).toBe("hoadon.png");
  });

  it("bỏ hẳn model_version khi người dùng để trống, để service tự chọn default", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} }));
    const file = new File([new Uint8Array([1])], "a.png", { type: "image/png" });
    await gateway.invokeUpload("ocr", file, null);
    expect((lastCall()[1].body as FormData).has("model_version")).toBe(false);
  });

  it("không tự đặt content-type: boundary của multipart phải do runtime sinh", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ trace_id: "t1", mode: "sync", run_id: null, result: null }));
    const file = new File([new Uint8Array([1])], "a.png", { type: "image/png" });
    await gateway.invokeUpload("ocr", file, null);
    expect(new Headers(lastCall()[1].headers).get("content-type")).toBeNull();
  });
});

describe("ánh xạ lỗi", () => {
  it("giữ nguyên mã HTTP, code và trace_id gateway trả về", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ code: "model_unavailable", message: "service 'ocr' đang không phản hồi", trace_id: "abc" }, 503),
    );
    await expect(gateway.listServices()).rejects.toMatchObject({
      status: 503,
      code: "model_unavailable",
      message: "service 'ocr' đang không phản hồi",
      traceId: "abc",
    });
  });

  it("vẫn ra GatewayError khi thân lỗi không phải JSON", async () => {
    fetchMock.mockResolvedValue(new Response("<html>502 Bad Gateway</html>", { status: 502 }));
    const error = await gateway.listHosts().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(GatewayError);
    expect((error as GatewayError).status).toBe(502);
  });

  it("không để lộ token trong thông điệp lỗi 401", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ code: "bad_input", message: "token không hợp lệ" }, 401));
    const error = await gateway.listHosts().catch((e: unknown) => e);
    expect(JSON.stringify(error, Object.getOwnPropertyNames(error))).not.toContain("token-gateway");
  });
});
