import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunsTable } from "@/components/RunsTable";
import type { RunRecord } from "@/lib/types";

function run(overrides: Partial<RunRecord> & { id: string }): RunRecord {
  return {
    trace_id: "t1", service: "ocr", model_version: "paddleocr-v4-vi", mode: "sync",
    status: "ok", input_uri: null, output: { full_text: "x", boxes: [] },
    latency_ms: 320, error: null, created_at: "2026-08-19T07:05:09Z", ...overrides,
  };
}

const filters = { limit: 50 };

describe("RunsTable", () => {
  it("hiện từng run kèm service, model, độ trễ và thời điểm", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={1} offset={0} filters={filters} />);
    const row = screen.getByRole("row", { name: /r1|paddleocr/ });
    expect(within(row).getByText("ocr")).toBeInTheDocument();
    expect(within(row).getByText("paddleocr-v4-vi")).toBeInTheDocument();
    expect(within(row).getByText("320 ms")).toBeInTheDocument();
    expect(within(row).getByText("2026-08-19 07:05:09")).toBeInTheDocument();
  });

  it("phân biệt run lỗi và hiện nguyên nhân", () => {
    render(
      <RunsTable
        runs={[run({ id: "r2", status: "failed", latency_ms: null, output: null, error: "service trả 500: hết VRAM" })]}
        total={1} offset={0} filters={filters}
      />,
    );
    const row = screen.getByRole("row", { name: /r2|hết VRAM/ });
    expect(within(row).getByText("failed")).toBeInTheDocument();
    expect(within(row).getByText(/hết VRAM/)).toBeInTheDocument();
    expect(within(row).getByText("—")).toBeInTheDocument();
  });

  it("hiện gạch ngang khi chưa biết model", () => {
    // model_version="" trong DB được chuẩn hoá về null; hiện chuỗi rỗng thì ô trông như lỗi render.
    render(<RunsTable runs={[run({ id: "r3", model_version: null })]} total={1} offset={0} filters={filters} />);
    expect(within(screen.getByRole("row", { name: /r3/ })).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("mỗi dòng dẫn tới trang chi tiết run", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={1} offset={0} filters={filters} />);
    expect(screen.getByRole("link", { name: /chi tiết/i })).toHaveAttribute("href", "/runs/r1");
  });

  it("trace_id bấm được để lọc mọi run cùng trace — đó là cách xem shadow-run", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={1} offset={0} filters={filters} />);
    expect(screen.getByRole("link", { name: "t1" })).toHaveAttribute("href", "/runs?trace_id=t1&limit=50");
  });

  it("cắt ngắn trace dài nhưng giữ nguyên bản đầy đủ để copy", () => {
    // trace_id thật dài 32 ký tự và sẽ nuốt hết bề ngang bảng. Cắt hiển thị,
    // nhưng title phải là bản đầy đủ — người ta cần chuỗi đó để tra log.
    const dai = "0893462620b1488b958d234272ee6cd7";
    render(<RunsTable runs={[run({ id: "r9", trace_id: dai })]} total={1} offset={0} filters={filters} />);
    const link = screen.getByRole("link", { name: /^0893462620b1/ });
    expect(link).toHaveAttribute("title", dai);
    expect(link.textContent).not.toBe(dai);
  });

  it("đặt sẵn giá trị lọc hiện tại vào form", () => {
    render(<RunsTable runs={[]} total={0} offset={0} filters={{ service: "asr", status: "failed", limit: 50 }} />);
    expect(screen.getByLabelText("Service")).toHaveValue("asr");
    expect(screen.getByLabelText("Trạng thái")).toHaveValue("failed");
  });

  it("hiện tổng số và khoảng đang xem", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={137} offset={50} filters={filters} />);
    expect(screen.getByText("51–51 / 137")).toBeInTheDocument();
  });

  it("khoá nút Trước ở trang đầu", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={137} offset={0} filters={filters} />);
    expect(screen.getByText("Trước")).not.toHaveAttribute("href");
  });

  it("khoá nút Sau ở trang cuối", () => {
    // offset 100 + 1 dòng = 101 = total: không còn gì phía sau.
    render(<RunsTable runs={[run({ id: "r1" })]} total={101} offset={100} filters={filters} />);
    expect(screen.getByText("Sau")).not.toHaveAttribute("href");
  });

  it("nút Sau giữ nguyên bộ lọc", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={137} offset={0} filters={{ service: "ocr", limit: 50 }} />);
    expect(screen.getByRole("link", { name: "Sau" })).toHaveAttribute("href", "/runs?service=ocr&limit=50&offset=50");
  });

  it("nói rõ khi bộ lọc không khớp run nào", () => {
    render(<RunsTable runs={[]} total={0} offset={0} filters={filters} />);
    expect(screen.getByText(/không có run nào khớp/i)).toBeInTheDocument();
  });
});
