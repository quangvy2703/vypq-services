import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Playground } from "@/components/Playground";
import type { HostState, ServiceState } from "@/lib/types";

const ocrService: ServiceState = {
  info: {
    name: "ocr", task: "ocr", capability_input: "image", capability_output: "text_boxes",
    version: "0.1.0", invoke_path: "/v1/ocr", default_model: "paddleocr-v4-vi",
  },
  base_url: "http://ocr:8000", status: "ok", last_seen_at: null,
};

const hosts: HostState[] = [
  {
    name: "a100", url: "https://a100.ngrok.app", healthy: true, last_seen_at: null, last_error: null,
    models: [
      { id: "paddleocr-v4-vi", task: "ocr", kind: "opensource", runner: "paddle", loaded: true, available: true, vram_mb: 1200, base: null, trained_on: null },
      { id: "vietocr-ft-invoice", task: "ocr", kind: "finetuned", runner: "vietocr", loaded: true, available: true, vram_mb: 900, base: "vietocr-base", trained_on: "invoice-vi-v2" },
    ],
  },
];

function ocrOutput(text: string) {
  // Bọc `text` trong một câu dài hơn thay vì dùng nguyên văn: OcrViewer luôn hiện
  // box.text ở bảng và full_text ở khối "Toàn văn", nên nếu để `text` (thường là
  // chính tên model, xem cách gọi bên dưới) trùng khớp tuyệt đối với modelLabel
  // thì getByText(tên model) trong panel sẽ khớp cả ba chỗ — Badge lẫn hai chỗ
  // này — và ném lỗi "multiple elements" dù DOM không có gì sai.
  const full = `văn bản mẫu (${text})`;
  return {
    full_text: full,
    boxes: [{ id: 1, polygon: [[1, 1], [9, 1], [9, 5], [1, 5]], text: full, confidence: 0.9, ignore: false }],
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn(() => "blob:gia-lap"),
    revokeObjectURL: vi.fn(),
  }));
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/invoke") {
      const model = String((init?.body as FormData).get("model_version") ?? "mac-dinh");
      return new Response(
        JSON.stringify({ trace_id: `t-${model}`, mode: "sync", run_id: `r-${model}`, result: ocrOutput(model) }),
        { status: 200 },
      );
    }
    const runId = url.slice("/api/runs/".length);
    return new Response(JSON.stringify({ id: runId, latency_ms: runId.includes("vietocr") ? 900 : 320 }), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function setup() {
  const user = userEvent.setup();
  render(<Playground services={[ocrService]} hosts={hosts} />);
  await user.upload(screen.getByLabelText(/tệp đầu vào/i), new File([new Uint8Array([1])], "hoadon.png", { type: "image/png" }));
  return user;
}

describe("Playground — so sánh nhiều model", () => {
  it("liệt kê các model có thể so sánh thêm", async () => {
    await setup();
    expect(screen.getByRole("checkbox", { name: /paddleocr-v4-vi/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ })).toBeInTheDocument();
  });

  it("chạy một lần cho model chính và mỗi model được tick", async () => {
    const user = await setup();
    await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    await waitFor(() => {
      const invokes = fetchMock.mock.calls.filter((call) => call[0] === "/api/invoke");
      expect(invokes).toHaveLength(2);
    });
  });

  it("không chạy hai lần cho cùng một model khi tick trùng model chính", async () => {
    const user = await setup();
    await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
    await user.click(screen.getByRole("checkbox", { name: /paddleocr-v4-vi/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    await waitFor(() => expect(screen.getAllByTestId("ket-qua")).toHaveLength(1));
  });

  it("hiện kết quả từng model cạnh nhau, mỗi bảng ghi tên model của nó", async () => {
    const user = await setup();
    await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    const panels = await screen.findAllByTestId("ket-qua");
    expect(panels).toHaveLength(2);
    expect(within(panels[0] as HTMLElement).getByText("paddleocr-v4-vi")).toBeInTheDocument();
    expect(within(panels[1] as HTMLElement).getByText("vietocr-ft-invoice")).toBeInTheDocument();
  });

  it("hiện độ trễ thật lấy từ bản ghi run, không đo bằng đồng hồ trình duyệt", async () => {
    const user = await setup();
    await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    const panels = await screen.findAllByTestId("ket-qua");
    expect(within(panels[0] as HTMLElement).getByText("320 ms")).toBeInTheDocument();
    expect(within(panels[1] as HTMLElement).getByText("900 ms")).toBeInTheDocument();
  });

  it("hiện thống kê mô tả cho từng model", async () => {
    const user = await setup();
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    const panels = await screen.findAllByTestId("ket-qua");
    expect(within(panels[0] as HTMLElement).getByText("Số vùng chữ")).toBeInTheDocument();
  });

  it("một model lỗi không kéo đổ kết quả của model kia", async () => {
    // Đây là lý do dùng allSettled: model fine-tune chưa tải được checkpoint là
    // chuyện thường, và nó không được che mất kết quả của model open-source.
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/invoke") {
        const model = String((init?.body as FormData).get("model_version") ?? "");
        if (model === "vietocr-ft-invoice") {
          return new Response(JSON.stringify({ code: "model_unavailable", message: "chưa tải được checkpoint" }), { status: 503 });
        }
        return new Response(JSON.stringify({ trace_id: "t1", mode: "sync", run_id: "r1", result: ocrOutput("ok") }), { status: 200 });
      }
      return new Response(JSON.stringify({ id: "r1", latency_ms: 320 }), { status: 200 });
    });

    const user = await setup();
    await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    const panels = await screen.findAllByTestId("ket-qua");
    expect(panels).toHaveLength(2);
    expect(within(panels[1] as HTMLElement).getByRole("alert")).toHaveTextContent(/chưa tải được checkpoint/);
    expect(within(panels[0] as HTMLElement).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("một model bị lỗi MẠNG cũng không kéo đổ kết quả model kia", () => {
    // Khác hẳn ca 503 ở trên: 503 là response hợp lệ nên runOne tự bắt và trả
    // RunOutcome, promise không bao giờ reject — nghĩa là ca đó chạy giống hệt
    // nhau với Promise.all lẫn Promise.allSettled. Chỉ khi fetch NÉM (mất mạng,
    // gateway rớt giữa chừng) mới phân biệt được hai cái, và đó mới là lý do
    // Promise.allSettled tồn tại ở đây.
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/invoke") {
        const model = String((init?.body as FormData).get("model_version") ?? "");
        if (model === "vietocr-ft-invoice") throw new TypeError("Failed to fetch");
        return new Response(
          JSON.stringify({ trace_id: "t1", mode: "sync", run_id: "r1", result: ocrOutput("ok") }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ id: "r1", latency_ms: 320 }), { status: 200 });
    });

    return (async () => {
      const user = await setup();
      await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
      await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
      await user.click(screen.getByRole("button", { name: "Chạy thử" }));

      const panels = await screen.findAllByTestId("ket-qua");
      expect(panels).toHaveLength(2);
      expect(within(panels[0] as HTMLElement).queryByRole("alert")).not.toBeInTheDocument();
      expect(within(panels[0] as HTMLElement).getByText("320 ms")).toBeInTheDocument();
      expect(within(panels[1] as HTMLElement).getByRole("alert")).toHaveTextContent(/Failed to fetch/);
    })();
  });

  it("vẫn hiện kết quả khi không lấy được độ trễ", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/invoke") {
        return new Response(JSON.stringify({ trace_id: "t1", mode: "sync", run_id: "r1", result: ocrOutput("ok") }), { status: 200 });
      }
      return new Response("{}", { status: 500 });
    });
    const user = await setup();
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));
    const panel = (await screen.findAllByTestId("ket-qua"))[0] as HTMLElement;
    expect(within(panel).getByText("—")).toBeInTheDocument();
  });

  it("bỏ tick khi đổi service — model của service cũ không thuộc service mới", async () => {
    const user = await setup();
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.selectOptions(screen.getByLabelText("Service"), "ocr");
    expect(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ })).not.toBeChecked();
  });
});
