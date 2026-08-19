import { describe, expect, it } from "vitest";

import { acceptForInput, capabilityOutputFor, isUsable, statusTone, viewerFor } from "@/lib/capability";
import type { ServiceState } from "@/lib/types";

describe("acceptForInput", () => {
  it("lọc theo ảnh cho service OCR", () => {
    expect(acceptForInput("image")).toBe("image/*");
  });

  it("lọc theo âm thanh cho service ASR", () => {
    expect(acceptForInput("audio")).toBe("audio/*");
  });

  it.each(["bytes", "video", "", "thu-gi-do-moi"])(
    "nhận mọi file khi chưa biết capability %j",
    (capability) => {
      // Spec §3.8: service thứ ba cắm vào phải dùng được ngay. Chặn upload vì
      // không nhận ra capability là biến "chưa hỗ trợ đẹp" thành "không dùng được".
      expect(acceptForInput(capability)).toBe("*/*");
    },
  );
});

describe("viewerFor", () => {
  it("chọn viewer bbox cho text_boxes", () => {
    expect(viewerFor("text_boxes")).toBe("text_boxes");
  });

  it("chọn viewer transcript cho transcript", () => {
    expect(viewerFor("transcript")).toBe("transcript");
  });

  it.each(["json", "embedding", ""])("rơi về xem JSON thô với %j", (capability) => {
    expect(viewerFor(capability)).toBe("json");
  });
});

const usable: ServiceState = {
  info: {
    name: "ocr", task: "ocr", capability_input: "image", capability_output: "text_boxes",
    version: "0.1.0", invoke_path: "/v1/ocr", default_model: "paddleocr-v4-vi",
  },
  base_url: "http://ocr:8000",
  status: "ok",
  last_seen_at: "2026-08-19T06:59:00Z",
};

describe("isUsable", () => {
  it("service khoẻ và đã biết info thì dùng được", () => {
    expect(isUsable(usable)).toBe(true);
  });

  it("info=null thì KHÔNG dùng được, dù trạng thái là gì", () => {
    // info=null nghĩa là gateway chưa từng poll được, nên chưa biết invoke_path.
    // Cho chọn ở playground = gửi request vào hư không.
    expect(isUsable({ ...usable, info: null, status: "ok" })).toBe(false);
  });

  it("service down thì không dùng được", () => {
    expect(isUsable({ ...usable, status: "down" })).toBe(false);
  });

  it("service degraded vẫn cho gọi — nó vẫn trả lời được", () => {
    expect(isUsable({ ...usable, status: "degraded" })).toBe(true);
  });
});

describe("statusTone", () => {
  it.each([
    ["ok", "ok"],
    ["degraded", "warn"],
    ["down", "bad"],
  ] as const)("ánh xạ %s sang tone %s", (status, tone) => {
    expect(statusTone(status)).toBe(tone);
  });
});

describe("capabilityOutputFor", () => {
  const asr: ServiceState = {
    info: {
      name: "asr", task: "asr", capability_input: "audio", capability_output: "transcript",
      version: "0.1.0", invoke_path: "/v1/asr", default_model: "whisper-large-v3",
    },
    base_url: "http://asr:8000",
    status: "ok",
    last_seen_at: null,
  };

  it("đọc capability từ chính service đã chạy run", () => {
    expect(capabilityOutputFor([usable, asr], "asr")).toBe("transcript");
  });

  it("KHÔNG suy từ tên service — service tên 'ocr' vẫn phải đọc capability đã khai", () => {
    // Tên chỉ là nhãn trong config/services.yaml; capability là thứ service tự
    // khai qua /v1/info. Đoán từ tên làm dashboard hiện output qua viewer của
    // task khác ngay khi hai thứ đó lệch nhau.
    const doiTen: ServiceState = {
      ...usable,
      info: { ...usable.info!, name: "ocr", capability_output: "transcript" },
    };
    expect(capabilityOutputFor([doiTen], "ocr")).toBe("transcript");
  });

  it("rơi về json khi không khớp service nào", () => {
    expect(capabilityOutputFor([usable], "khong-ton-tai")).toBe("json");
  });

  it("rơi về json khi service chưa từng được poll (info=null)", () => {
    const chuaBiet: ServiceState = { info: null, base_url: "http://ner:8000", status: "down", last_seen_at: null };
    expect(capabilityOutputFor([chuaBiet], "ner")).toBe("json");
  });

  it("rơi về json khi danh sách service rỗng", () => {
    expect(capabilityOutputFor([], "ocr")).toBe("json");
  });
});
