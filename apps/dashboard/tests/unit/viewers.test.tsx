import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AsrViewer } from "@/components/viewers/AsrViewer";
import { OcrViewer } from "@/components/viewers/OcrViewer";
import { ResultViewer } from "@/components/viewers/ResultViewer";
import type { AsrResult, OcrResult } from "@/lib/types";

const ocr: OcrResult = {
  full_text: "HOÁ ĐƠN\nTổng cộng 120000",
  boxes: [
    { id: 1, polygon: [[10, 10], [110, 10], [110, 40], [10, 40]], text: "HOÁ ĐƠN", confidence: 0.98, ignore: false },
    { id: 2, polygon: [[10, 50], [200, 50], [200, 80], [10, 80]], text: "Tổng cộng 120000", confidence: 0.71, ignore: false },
    { id: 3, polygon: [[0, 90], [20, 90], [20, 100], [0, 100]], text: "nhiễu", confidence: 0.2, ignore: true },
  ],
};

const asr: AsrResult = {
  text: "xin chào các bạn",
  segments: [
    { start: 0, end: 1.5, text: "xin chào", speaker: "A" },
    { start: 1.5, end: 3.25, text: "các bạn", speaker: "B" },
  ],
};

describe("OcrViewer", () => {
  it("vẽ một polygon cho mỗi box", () => {
    const { container } = render(<OcrViewer result={ocr} imageUrl={null} />);
    expect(container.querySelectorAll("svg polygon")).toHaveLength(3);
  });

  it("dùng toạ độ gốc làm điểm của polygon, không tự nhân tỉ lệ", () => {
    const { container } = render(<OcrViewer result={ocr} imageUrl={null} />);
    const first = container.querySelector("svg polygon");
    expect(first?.getAttribute("points")).toBe("10,10 110,10 110,40 10,40");
  });

  it("khi không có ảnh thì viewBox suy từ chính các box", () => {
    // Đây là đường đi của trang chi tiết run: run sync ghi input_uri=null.
    const { container } = render(<OcrViewer result={ocr} imageUrl={null} />);
    expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 200 100");
  });

  it("khi có ảnh thì viewBox theo kích thước tự nhiên của ảnh", () => {
    const { container } = render(<OcrViewer result={ocr} imageUrl="blob:hoadon" />);
    const image = screen.getByRole("img", { name: /ảnh đầu vào/i });
    Object.defineProperty(image, "naturalWidth", { value: 1240, configurable: true });
    Object.defineProperty(image, "naturalHeight", { value: 1754, configurable: true });
    fireEvent.load(image);
    expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 1240 1754");
  });

  it("liệt kê text của từng box kèm độ tin cậy", () => {
    render(<OcrViewer result={ocr} imageUrl={null} />);
    const row = screen.getByRole("row", { name: /HOÁ ĐƠN/ });
    expect(within(row).getByText("0.98")).toBeInTheDocument();
  });

  it("đánh dấu box bị bỏ qua thay vì giấu", () => {
    render(<OcrViewer result={ocr} imageUrl={null} />);
    expect(screen.getByRole("row", { name: /nhiễu/ })).toHaveAttribute("data-ignored", "true");
  });

  it("làm nổi polygon tương ứng khi rê vào một dòng text", async () => {
    const user = userEvent.setup();
    const { container } = render(<OcrViewer result={ocr} imageUrl={null} />);
    await user.hover(screen.getByRole("row", { name: /Tổng cộng 120000/ }));
    const selected = container.querySelectorAll('svg polygon[data-selected="true"]');
    expect(selected).toHaveLength(1);
    expect(selected[0]?.getAttribute("points")).toBe("10,50 200,50 200,80 10,80");
  });

  it("hiện toàn văn để copy, dưới dạng một khối text liền", () => {
    // Toàn văn trùng nội dung với một box trong bảng, nên phải khoanh vùng truy
    // vấn vào đúng khối này. Khẳng định thẳng vào textContent của <pre>: nếu ai
    // đó cắt nó thành nhiều node cho dễ tìm thì bôi đen copy sẽ ra sai.
    const { container } = render(<OcrViewer result={ocr} imageUrl={null} />);
    const block = container.querySelector("pre");
    expect(block).not.toBeNull();
    expect(block?.textContent).toBe(ocr.full_text);
    expect(block?.childNodes).toHaveLength(1);
  });

  it("vẫn dựng được viewBox hợp lệ khi không có box nào", () => {
    // svg có chiều bằng 0 thì không vẽ ra gì cả, và trang chi tiết run (không
    // có ảnh gốc) rơi vào đúng nhánh này mỗi khi model trả rỗng.
    const { container } = render(<OcrViewer result={{ full_text: "", boxes: [] }} imageUrl={null} />);
    expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 1 1");
  });

  it("nói rõ khi model không tìm thấy chữ nào", () => {
    render(<OcrViewer result={{ full_text: "", boxes: [] }} imageUrl={null} />);
    expect(screen.getByText(/không tìm thấy chữ nào/i)).toBeInTheDocument();
  });
});

describe("AsrViewer", () => {
  it("liệt kê từng segment kèm mốc thời gian và người nói", () => {
    render(<AsrViewer result={asr} audioUrl={null} onSeek={vi.fn()} />);
    const row = screen.getByRole("row", { name: /các bạn/ });
    expect(within(row).getByText("00:01.5 → 00:03.2")).toBeInTheDocument();
    expect(within(row).getByText("B")).toBeInTheDocument();
  });

  it("hiện toàn văn transcript", () => {
    render(<AsrViewer result={asr} audioUrl={null} onSeek={vi.fn()} />);
    expect(screen.getByText("xin chào các bạn")).toBeInTheDocument();
  });

  it("gọi onSeek với mốc bắt đầu khi bấm vào segment", async () => {
    const onSeek = vi.fn();
    const user = userEvent.setup();
    render(<AsrViewer result={asr} audioUrl="blob:am-thanh" onSeek={onSeek} />);
    await user.click(screen.getByRole("button", { name: /nghe từ 00:01.5/i }));
    expect(onSeek).toHaveBeenCalledWith(1.5);
  });

  it("không hiện nút nghe khi không có file âm thanh (trang lịch sử)", () => {
    render(<AsrViewer result={asr} audioUrl={null} onSeek={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /nghe từ/i })).not.toBeInTheDocument();
  });

  it("nói rõ khi model không nghe ra gì", () => {
    render(<AsrViewer result={{ text: "", segments: [] }} audioUrl={null} onSeek={vi.fn()} />);
    expect(screen.getByText(/không nhận ra lời nào/i)).toBeInTheDocument();
  });
});

describe("ResultViewer", () => {
  it("chọn viewer bbox theo capability text_boxes", () => {
    const { container } = render(
      <ResultViewer capabilityOutput="text_boxes" output={ocr as unknown as Record<string, unknown>} imageUrl={null} audioUrl={null} />,
    );
    expect(container.querySelectorAll("svg polygon")).toHaveLength(3);
  });

  it("chọn viewer transcript theo capability transcript", () => {
    render(
      <ResultViewer capabilityOutput="transcript" output={asr as unknown as Record<string, unknown>} imageUrl={null} audioUrl={null} />,
    );
    expect(screen.getByText("xin chào các bạn")).toBeInTheDocument();
  });

  it("hiện JSON thô cho capability chưa biết — service thứ ba cắm vào vẫn xem được", () => {
    render(
      <ResultViewer capabilityOutput="embedding" output={{ vector: [0.1, 0.2] }} imageUrl={null} audioUrl={null} />,
    );
    expect(screen.getByText(/"vector"/)).toBeInTheDocument();
  });

  it("rơi về JSON thô khi payload không khớp capability đã khai", () => {
    // Model-host bản mới đổi hình dạng output là chuyện xảy ra được; hiện thô
    // vẫn hơn trang trắng.
    render(
      <ResultViewer capabilityOutput="text_boxes" output={{ khong_phai_boxes: 1 }} imageUrl={null} audioUrl={null} />,
    );
    expect(screen.getByText(/khong_phai_boxes/)).toBeInTheDocument();
  });

  it("nói rõ khi run chưa có output", () => {
    // Run async lúc mới nhận, và mọi run failed, đều có output=null.
    render(<ResultViewer capabilityOutput="text_boxes" output={null} imageUrl={null} audioUrl={null} />);
    expect(screen.getByText(/chưa có kết quả/i)).toBeInTheDocument();
  });
});
