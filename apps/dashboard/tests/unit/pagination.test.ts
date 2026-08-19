import { describe, expect, it } from "vitest";

import { buildRunsHref } from "@/lib/pagination";

describe("buildRunsHref", () => {
  it("giữ nguyên bộ lọc khi sang trang", () => {
    expect(buildRunsHref({ service: "ocr", status: "failed", limit: 50 }, 50))
      .toBe("/runs?service=ocr&status=failed&limit=50&offset=50");
  });

  it("bỏ bộ lọc rỗng khỏi URL", () => {
    expect(buildRunsHref({ service: "", status: undefined, limit: 50 }, 0)).toBe("/runs?limit=50");
  });

  it("không ghi offset=0 vào URL — trang đầu là đường dẫn sạch", () => {
    expect(buildRunsHref({ limit: 50 }, 0)).toBe("/runs?limit=50");
  });

  it("không cho offset âm", () => {
    expect(buildRunsHref({ limit: 50 }, -50)).toBe("/runs?limit=50");
  });

  it("mã hoá trace_id có ký tự đặc biệt", () => {
    expect(buildRunsHref({ trace_id: "a b&c", limit: 50 }, 0)).toBe("/runs?trace_id=a+b%26c&limit=50");
  });
});
