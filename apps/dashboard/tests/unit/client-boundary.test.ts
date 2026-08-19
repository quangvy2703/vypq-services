// @vitest-environment node
import { readFileSync, readdirSync } from "node:fs";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("../../src", import.meta.url));

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return [".ts", ".tsx"].includes(extname(entry.name)) ? [full] : [];
  });
}

const files = sourceFiles(SRC).map((path) => ({ path, text: readFileSync(path, "utf8") }));
const clientFiles = files.filter((file) => /^\s*["']use client["']/m.test(file.text));

describe("ranh giới client/server", () => {
  it("có ít nhất một client component để phép kiểm này không rỗng", () => {
    expect(clientFiles.length).toBeGreaterThan(0);
  });

  it.each(["@/lib/gateway", "@/lib/env"])(
    "không client component nào import %s",
    (module) => {
      // Import từ client component sẽ kéo token gateway vào bundle trình duyệt.
      const offenders = clientFiles.filter((file) => file.text.includes(module)).map((file) => file.path);
      expect(offenders).toEqual([]);
    },
  );

  it("không file nào đặt token gateway vào biến NEXT_PUBLIC_", () => {
    // Mọi NEXT_PUBLIC_* đều được nhúng thẳng vào JS gửi cho trình duyệt.
    const offenders = files
      .filter((file) => /NEXT_PUBLIC_\w*(TOKEN|SECRET|PASSWORD)/.test(file.text))
      .map((file) => file.path);
    expect(offenders).toEqual([]);
  });

  it("không nơi nào gọi /v1/discovery/hosts — endpoint đó mang token của máy GPU", () => {
    const offenders = files.filter((file) => file.text.includes("discovery/hosts")).map((file) => file.path);
    expect(offenders).toEqual([]);
  });
});
