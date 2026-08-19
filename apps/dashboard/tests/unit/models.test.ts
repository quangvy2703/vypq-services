import { describe, expect, it } from "vitest";

import { modelsForTask } from "@/lib/models";
import type { HostState, ModelInfo } from "@/lib/types";

function model(overrides: Partial<ModelInfo> & { id: string }): ModelInfo {
  return {
    task: "ocr", kind: "opensource", runner: "paddle", loaded: false,
    available: true, vram_mb: 0, base: null, trained_on: null, ...overrides,
  };
}

function host(name: string, healthy: boolean, models: ModelInfo[]): HostState {
  return { name, url: `https://${name}.ngrok.app`, healthy, models, last_seen_at: null, last_error: null };
}

describe("modelsForTask", () => {
  it("chỉ lấy model đúng task — service ocr không gọi được model asr", () => {
    const hosts = [host("a", true, [model({ id: "paddleocr" }), model({ id: "whisper", task: "asr" })])];
    expect(modelsForTask(hosts, "ocr").map((m) => m.id)).toEqual(["paddleocr"]);
  });

  it("bỏ hẳn model trên host đang chết", () => {
    // Chọn được một model không định tuyến tới đâu là bẫy: request đi ra rồi
    // chết ở tầng dưới với lỗi khó hiểu.
    const hosts = [host("chet", false, [model({ id: "paddleocr" })])];
    expect(modelsForTask(hosts, "ocr")).toEqual([]);
  });

  it("giữ model available=false nhưng đánh dấu lại", () => {
    const hosts = [host("a", true, [model({ id: "vietocr-ft", available: false })])];
    expect(modelsForTask(hosts, "ocr")).toEqual([
      { id: "vietocr-ft", kind: "opensource", hostName: "a", available: false },
    ]);
  });

  it("gộp model trùng id trên nhiều host thành một lựa chọn", () => {
    // Cùng một model id trên hai máy thuê là chuyện thường; hiện hai dòng giống
    // hệt nhau không cho người dùng thêm thông tin gì, chỉ gây rối.
    const hosts = [host("a", true, [model({ id: "paddleocr" })]), host("b", true, [model({ id: "paddleocr" })])];
    expect(modelsForTask(hosts, "ocr")).toHaveLength(1);
  });

  it("ưu tiên bản available khi cùng id có trên host này hỏng, host kia lành", () => {
    const hosts = [
      host("a", true, [model({ id: "paddleocr", available: false })]),
      host("b", true, [model({ id: "paddleocr", available: true })]),
    ];
    expect(modelsForTask(hosts, "ocr")[0]).toMatchObject({ available: true, hostName: "b" });
  });

  it("sắp xếp theo id để danh sách không nhảy giữa các lần poll", () => {
    const hosts = [host("a", true, [model({ id: "zebra" }), model({ id: "alpha" })])];
    expect(modelsForTask(hosts, "ocr").map((m) => m.id)).toEqual(["alpha", "zebra"]);
  });

  it("phân biệt model fine-tune", () => {
    const hosts = [host("a", true, [model({ id: "vietocr-ft", kind: "finetuned" })])];
    expect(modelsForTask(hosts, "ocr")[0]?.kind).toBe("finetuned");
  });
});
