import { afterEach, describe, expect, it, vi } from "vitest";

import { getServerEnv } from "@/lib/env";

afterEach(() => {
  vi.unstubAllEnvs();
});

function stubAll(): void {
  vi.stubEnv("GATEWAY_TOKEN", "token-gateway");
  vi.stubEnv("DASHBOARD_PASSWORD", "matkhau");
  vi.stubEnv("SESSION_SECRET", "bi-mat-phien");
}

describe("getServerEnv", () => {
  it("đọc đủ ba bí mật và mặc định gatewayUrl về localhost", () => {
    stubAll();
    vi.stubEnv("GATEWAY_URL", "");
    const env = getServerEnv();
    expect(env.gatewayToken).toBe("token-gateway");
    expect(env.dashboardPassword).toBe("matkhau");
    expect(env.sessionSecret).toBe("bi-mat-phien");
    expect(env.gatewayUrl).toBe("http://localhost:8080");
  });

  it("cắt dấu / thừa ở cuối GATEWAY_URL", () => {
    // Nối "http://gateway:8080/" với "/v1/hosts" ra "//v1/hosts" — gateway trả 404
    // và triệu chứng trông hệt như route không tồn tại.
    stubAll();
    vi.stubEnv("GATEWAY_URL", "http://gateway:8080///");
    expect(getServerEnv().gatewayUrl).toBe("http://gateway:8080");
  });

  it.each(["GATEWAY_TOKEN", "DASHBOARD_PASSWORD", "SESSION_SECRET"])(
    "từ chối chạy khi thiếu %s",
    (name) => {
      stubAll();
      vi.stubEnv(name, "");
      expect(() => getServerEnv()).toThrow(new RegExp(`${name}.*từ chối khởi động`));
    },
  );

  it("coi biến chỉ có khoảng trắng là thiếu", () => {
    stubAll();
    vi.stubEnv("SESSION_SECRET", "   ");
    expect(() => getServerEnv()).toThrow(/SESSION_SECRET/);
  });

  it("giới hạn upload đúng 25 MB, khớp max_inline_mb của service", () => {
    stubAll();
    expect(getServerEnv().maxUploadBytes).toBe(25 * 1024 * 1024);
  });
});
