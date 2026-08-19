import { describe, expect, it } from "vitest";

import { asAsrResult, asOcrResult, boundingExtent } from "@/lib/results";

const box = { id: 1, polygon: [[0, 0], [10, 0], [10, 5], [0, 5]], text: "HOÁ ĐƠN", confidence: 0.98, ignore: false };

describe("asOcrResult", () => {
  it("nhận kết quả OCR hợp lệ", () => {
    const parsed = asOcrResult({ full_text: "HOÁ ĐƠN", boxes: [box] });
    expect(parsed?.boxes).toHaveLength(1);
    expect(parsed?.full_text).toBe("HOÁ ĐƠN");
  });

  it("nhận kết quả rỗng — ảnh không có chữ là kết quả hợp lệ", () => {
    expect(asOcrResult({ full_text: "", boxes: [] })).toEqual({ full_text: "", boxes: [] });
  });

  it("bù full_text rỗng khi service không trả trường đó", () => {
    expect(asOcrResult({ boxes: [box] })?.full_text).toBe("");
  });

  it("bỏ box có polygon dưới 4 điểm thay vì vẽ hình méo", () => {
    const parsed = asOcrResult({ full_text: "x", boxes: [box, { ...box, id: 2, polygon: [[0, 0], [1, 1]] }] });
    expect(parsed?.boxes.map((b) => b.id)).toEqual([1]);
  });

  it("bỏ box có toạ độ không phải số", () => {
    const parsed = asOcrResult({ full_text: "x", boxes: [{ ...box, id: 3, polygon: [["a", 0], [1, 1], [2, 2], [3, 3]] }] });
    expect(parsed?.boxes).toEqual([]);
  });

  it.each([null, undefined, 42, "chuoi", { segments: [] }])(
    "trả null cho payload không phải OCR: %j",
    (payload) => {
      // ResultViewer dựa vào null này để rơi về xem JSON thô thay vì hiện trang trắng.
      expect(asOcrResult(payload)).toBeNull();
    },
  );
});

describe("asAsrResult", () => {
  it("nhận transcript hợp lệ", () => {
    const parsed = asAsrResult({ text: "xin chào", segments: [{ start: 0, end: 1.5, text: "xin chào", speaker: "A" }] });
    expect(parsed?.segments).toHaveLength(1);
    expect(parsed?.segments[0]?.speaker).toBe("A");
  });

  it("bù speaker null khi model không tách người nói", () => {
    const parsed = asAsrResult({ text: "a", segments: [{ start: 0, end: 1, text: "a" }] });
    expect(parsed?.segments[0]?.speaker).toBeNull();
  });

  it("bỏ segment có mốc thời gian không phải số", () => {
    const parsed = asAsrResult({ text: "a", segments: [{ start: "x", end: 1, text: "a" }] });
    expect(parsed?.segments).toEqual([]);
  });

  it.each([null, 42, { boxes: [] }])("trả null cho payload không phải ASR: %j", (payload) => {
    expect(asAsrResult(payload)).toBeNull();
  });
});

describe("boundingExtent", () => {
  it("bao trọn mọi polygon", () => {
    expect(boundingExtent([box, { ...box, id: 2, polygon: [[0, 0], [40, 0], [40, 30], [0, 30]] }]))
      .toEqual({ width: 40, height: 30 });
  });

  it("trả khung tối thiểu khi không có box — svg viewBox 0×0 không hiển thị được", () => {
    expect(boundingExtent([])).toEqual({ width: 1, height: 1 });
  });

  it("bỏ qua toạ độ âm chứ không để viewBox nhỏ hơn 1", () => {
    expect(boundingExtent([{ ...box, polygon: [[-5, -5], [-1, -5], [-1, -1], [-5, -1]] }]))
      .toEqual({ width: 1, height: 1 });
  });
});
