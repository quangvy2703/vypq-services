import { render, screen, waitFor } from "@testing-library/react";
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

const asrService: ServiceState = {
  info: {
    name: "asr", task: "asr", capability_input: "audio", capability_output: "transcript",
    version: "0.1.0", invoke_path: "/v1/asr", default_model: "whisper-large-v3",
  },
  base_url: "http://asr:8000", status: "ok", last_seen_at: null,
};

const unreachable: ServiceState = { info: null, base_url: "http://ner:8000", status: "down", last_seen_at: null };

const hosts: HostState[] = [
  {
    name: "a100", url: "https://a100.ngrok.app", healthy: true, last_seen_at: null, last_error: null,
    models: [
      { id: "paddleocr-v4-vi", task: "ocr", kind: "opensource", runner: "paddle", loaded: true, available: true, vram_mb: 1200, base: null, trained_on: null },
      { id: "vietocr-ft-invoice", task: "ocr", kind: "finetuned", runner: "vietocr", loaded: false, available: true, vram_mb: 0, base: "vietocr-base", trained_on: "invoice-vi-v2" },
      { id: "whisper-large-v3", task: "asr", kind: "opensource", runner: "whisper", loaded: false, available: true, vram_mb: 0, base: null, trained_on: null },
    ],
  },
];

const OCR_OUTPUT = {
  full_text: "HOÁ ĐƠN",
  boxes: [{ id: 1, polygon: [[1, 1], [9, 1], [9, 5], [1, 5]], text: "HOÁ ĐƠN", confidence: 0.9, ignore: false }],
};

let fetchMock: ReturnType<typeof vi.fn>;

function invokeOk(): Response {
  return new Response(JSON.stringify({ trace_id: "t1", mode: "sync", run_id: "r1", result: OCR_OUTPUT }), { status: 200 });
}

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue(invokeOk());
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn(() => "blob:gia-lap"),
    revokeObjectURL: vi.fn(),
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function pickFile(user: ReturnType<typeof userEvent.setup>, name = "hoadon.png", type = "image/png") {
  const input = screen.getByLabelText(/tệp đầu vào/i);
  await user.upload(input, new File([new Uint8Array([1, 2, 3])], name, { type }));
}

describe("Playground", () => {
  it("chỉ cho chọn service đã liên hệ được", () => {
    render(<Playground services={[ocrService, unreachable]} hosts={hosts} />);
    const select = screen.getByLabelText("Service") as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["ocr"]);
  });

  it("báo rõ khi không có service nào dùng được", () => {
    render(<Playground services={[unreachable]} hosts={hosts} />);
    expect(screen.getByText(/chưa có service nào dùng được/i)).toBeInTheDocument();
  });

  it("đặt accept của ô upload theo capability_input của service", () => {
    render(<Playground services={[ocrService]} hosts={hosts} />);
    expect(screen.getByLabelText(/tệp đầu vào/i)).toHaveAttribute("accept", "image/*");
  });

  it("đổi accept khi chuyển sang service ASR", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService, asrService]} hosts={hosts} />);
    await user.selectOptions(screen.getByLabelText("Service"), "asr");
    expect(screen.getByLabelText(/tệp đầu vào/i)).toHaveAttribute("accept", "audio/*");
  });

  it("chỉ liệt kê model đúng task của service đang chọn", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService, asrService]} hosts={hosts} />);
    expect(screen.getByLabelText(/model/i)).toHaveTextContent("paddleocr-v4-vi");
    await user.selectOptions(screen.getByLabelText("Service"), "asr");
    const select = screen.getByLabelText(/model/i) as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["", "whisper-large-v3"]);
  });

  it("mặc định để trống model, tức là dùng default_model của service", () => {
    render(<Playground services={[ocrService]} hosts={hosts} />);
    expect((screen.getByLabelText(/model/i) as HTMLSelectElement).value).toBe("");
  });

  it("chưa chọn file thì không cho chạy", () => {
    render(<Playground services={[ocrService]} hosts={hosts} />);
    expect(screen.getByRole("button", { name: "Chạy thử" })).toBeDisabled();
  });

  it("gửi service, model và file lên /api/invoke", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.selectOptions(screen.getByLabelText(/model/i), "vietocr-ft-invoice");
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/invoke");
    const body = init.body as FormData;
    expect(body.get("service")).toBe("ocr");
    expect(body.get("model_version")).toBe("vietocr-ft-invoice");
    expect((body.get("file") as File).name).toBe("hoadon.png");
  });

  it("vẽ overlay bbox trên đúng ảnh vừa upload", async () => {
    const user = userEvent.setup();
    const { container } = render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    await waitFor(() => expect(container.querySelectorAll("svg polygon")).toHaveLength(1));
    expect(screen.getByRole("img", { name: /ảnh đầu vào/i })).toHaveAttribute("src", "blob:gia-lap");
  });

  it("hiện trace_id và link tới run để lần ra lịch sử", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    expect(await screen.findByText("t1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /xem run/i })).toHaveAttribute("href", "/runs/r1");
  });

  it("hiện thông điệp lỗi của service thay vì im lặng", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ code: "model_unavailable", message: "service 'ocr' đang không phản hồi" }), { status: 503 }),
    );
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/service 'ocr' đang không phản hồi/);
  });

  it("khoá nút trong lúc đang chạy để không bắn hai request", async () => {
    let release: (value: Response) => void = () => {};
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => { release = resolve; }));
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));
    expect(await screen.findByRole("button", { name: /đang chạy/i })).toBeDisabled();
    release(invokeOk());
  });

  it("thu hồi object URL của ảnh cũ khi chọn file khác", async () => {
    // Không revoke thì mỗi lần thử một ảnh là giữ thêm một bản trong bộ nhớ tab.
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user, "anh1.png");
    await pickFile(user, "anh2.png");
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:gia-lap"));
  });

  it("xoá kết quả cũ khi đổi service — kết quả OCR không thuộc về service ASR", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService, asrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));
    await screen.findByText("t1");
    await user.selectOptions(screen.getByLabelText("Service"), "asr");
    expect(screen.queryByText("t1")).not.toBeInTheDocument();
  });
});
