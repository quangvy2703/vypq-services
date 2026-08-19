import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ServicesTable } from "@/components/ServicesTable";
import type { ServiceState } from "@/lib/types";

const ocr: ServiceState = {
  info: {
    name: "ocr", task: "ocr", capability_input: "image", capability_output: "text_boxes",
    version: "0.1.0", invoke_path: "/v1/ocr", default_model: "paddleocr-v4-vi",
  },
  base_url: "http://ocr:8000",
  status: "ok",
  last_seen_at: "2026-08-19T06:59:00Z",
};

const unknown: ServiceState = {
  info: null,
  base_url: "http://ner:8000",
  status: "down",
  last_seen_at: null,
};

describe("ServicesTable", () => {
  it("hiện tên, task, capability và model mặc định của service đã biết", () => {
    render(<ServicesTable services={[ocr]} />);
    const row = screen.getByRole("row", { name: /ocr/ });
    expect(within(row).getByText("ocr")).toBeInTheDocument();
    expect(within(row).getByText("image → text_boxes")).toBeInTheDocument();
    expect(within(row).getByText("paddleocr-v4-vi")).toBeInTheDocument();
    expect(within(row).getByText("khoẻ")).toBeInTheDocument();
  });

  it("nói rõ chưa liên hệ được và KHÔNG đoán task khi info=null", () => {
    render(<ServicesTable services={[unknown]} />);
    const row = screen.getByRole("row", { name: /ner/ });
    expect(within(row).getByText(/chưa liên hệ được/i)).toBeInTheDocument();
    // Suy task từ base_url là chỗ dễ sai nhất: "ner" trong URL không phải task.
    expect(within(row).queryByText("ocr")).not.toBeInTheDocument();
    expect(within(row).queryByText("asr")).not.toBeInTheDocument();
  });

  it("hiện base_url để lần ra container nào đang hỏng", () => {
    render(<ServicesTable services={[unknown]} />);
    expect(screen.getByText("http://ner:8000")).toBeInTheDocument();
  });

  it("hiện hướng dẫn khi config/services.yaml chưa khai service nào", () => {
    render(<ServicesTable services={[]} />);
    expect(screen.getByText(/chưa khai service nào/i)).toBeInTheDocument();
  });
});
