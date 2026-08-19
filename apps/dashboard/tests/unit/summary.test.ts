import { describe, expect, it } from "vitest";

import { summarize } from "@/lib/summary";

const ocr = {
  full_text: "HOÁ ĐƠN\nTổng 120000",
  boxes: [
    { id: 1, polygon: [[0, 0], [1, 0], [1, 1], [0, 1]], text: "HOÁ ĐƠN", confidence: 0.9, ignore: false },
    { id: 2, polygon: [[0, 2], [1, 2], [1, 3], [0, 3]], text: "Tổng 120000", confidence: 0.7, ignore: false },
    { id: 3, polygon: [[0, 4], [1, 4], [1, 5], [0, 5]], text: "x", confidence: 0.1, ignore: true },
  ],
};

const asr = {
  text: "xin chào các bạn",
  segments: [
    { start: 0, end: 1.5, text: "xin chào", speaker: "A" },
    { start: 1.5, end: 4, text: "các bạn", speaker: "B" },
  ],
};

function valueOf(stats: { label: string; value: string }[], label: string): string | undefined {
  return stats.find((stat) => stat.label === label)?.value;
}

describe("summarize cho OCR", () => {
  it("đếm số box không bị bỏ qua", () => {
    // Đếm cả box ignore sẽ làm model nhiễu nhiều trông như model đọc được nhiều hơn.
    expect(valueOf(summarize("text_boxes", ocr), "Số vùng chữ")).toBe("2");
  });

  it("đếm ký tự của toàn văn", () => {
    expect(valueOf(summarize("text_boxes", ocr), "Số ký tự")).toBe("19");
  });

  it("lấy độ tin cậy trung bình của các box được giữ", () => {
    expect(valueOf(summarize("text_boxes", ocr), "Độ tin cậy TB")).toBe("0.80");
  });

  it("hiện gạch ngang khi không box nào có độ tin cậy", () => {
    const noConfidence = { full_text: "a", boxes: [{ ...ocr.boxes[0], confidence: null }] };
    expect(valueOf(summarize("text_boxes", noConfidence), "Độ tin cậy TB")).toBe("—");
  });
});

describe("summarize cho ASR", () => {
  it("đếm số segment", () => {
    expect(valueOf(summarize("transcript", asr), "Số segment")).toBe("2");
  });

  it("đo tổng thời lượng có lời từ mốc cuối cùng", () => {
    expect(valueOf(summarize("transcript", asr), "Thời lượng")).toBe("00:04.0");
  });

  it("đếm ký tự transcript", () => {
    expect(valueOf(summarize("transcript", asr), "Số ký tự")).toBe("16");
  });
});

describe("summarize cho phần còn lại", () => {
  it("không bịa thống kê cho capability chưa biết", () => {
    expect(summarize("embedding", { vector: [1, 2] })).toEqual([]);
  });

  it("không bịa thống kê khi payload lệch capability đã khai", () => {
    expect(summarize("text_boxes", { khong_phai_boxes: 1 })).toEqual([]);
  });

  it("trả rỗng khi chưa có output", () => {
    expect(summarize("text_boxes", null)).toEqual([]);
  });
});
