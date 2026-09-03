import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Playground } from "@/components/Playground";
import type { HostState, ServiceState } from "@/lib/types";

const ocrService: ServiceState = {
  name: "ocr",
  info: {
    name: "ocr", task: "ocr", capability_input: "image", capability_output: "text_boxes",
    version: "0.1.0", invoke_path: "/v1/ocr", default_model: "paddleocr-v4-vi",
  },
  base_url: "http://ocr:8000", status: "ok", last_seen_at: null,
};

const asrService: ServiceState = {
  name: "asr",
  info: {
    name: "asr", task: "asr", capability_input: "audio", capability_output: "transcript",
    version: "0.1.0", invoke_path: "/v1/asr", default_model: "whisper-large-v3",
  },
  base_url: "http://asr:8000", status: "ok", last_seen_at: null,
};

const unreachable: ServiceState = { name: "ner", info: null, base_url: "http://ner:8000", status: "down", last_seen_at: null };

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
  fetchMock = vi.fn(async (url: string) =>
    url === "/api/invoke"
      ? invokeOk()
      : new Response(JSON.stringify({ id: "r1", latency_ms: 320 }), { status: 200 }),
  );
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
    expect(screen.getByLabelText(/^Model$/)).toHaveTextContent("paddleocr-v4-vi");
    await user.selectOptions(screen.getByLabelText("Service"), "asr");
    const select = screen.getByLabelText(/^Model$/) as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["", "whisper-large-v3"]);
  });

  it("mặc định để trống model, tức là dùng default_model của service", () => {
    render(<Playground services={[ocrService]} hosts={hosts} />);
    expect((screen.getByLabelText(/^Model$/) as HTMLSelectElement).value).toBe("");
  });

  it("chưa chọn file thì không cho chạy", () => {
    render(<Playground services={[ocrService]} hosts={hosts} />);
    expect(screen.getByRole("button", { name: "Chạy thử" })).toBeDisabled();
  });

  it("gửi service, model và file lên /api/invoke", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.selectOptions(screen.getByLabelText(/^Model$/), "vietocr-ft-invoice");
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const invokeCall = fetchMock.mock.calls.find((call) => call[0] === "/api/invoke");
    const [url, init] = invokeCall as [string, RequestInit];
    expect(url).toBe("/api/invoke");
    const body = init.body as FormData;
    expect(body.get("service")).toBe("ocr");
    expect(body.get("model_version")).toBe("vietocr-ft-invoice");
    expect((body.get("file") as File).name).toBe("hoadon.png");
  });

  it("gọi bằng KHOÁ ĐỊNH TUYẾN chứ không phải tên service tự khai", async () => {
    // Gateway tra cứu bằng khoá trong services.yaml. Gửi info.name khi hai tên
    // lệch nhau thì mọi lần chạy thử trả 404 "không có service" và không chỗ
    // nào nói vì sao.
    const lechTen = { ...ocrService, name: "docsvc", info: { ...ocrService.info!, name: "docreader" } };
    const user = userEvent.setup();
    render(<Playground services={[lechTen]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const invokeCall = fetchMock.mock.calls.find((call) => call[0] === "/api/invoke");
    const body = (invokeCall as [string, RequestInit])[1].body as FormData;
    expect(body.get("service")).toBe("docsvc");
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

  it("bỏ kết quả về trễ của service cũ khi người dùng đã đổi service", async () => {
    // Race thật: bấm Chạy trên OCR, đổi sang ASR trong lúc request còn bay, rồi
    // kết quả OCR mới về. Ghi thẳng vào state thì người dùng đang nhìn output
    // OCR qua viewer của ASR — đúng thứ mà việc xoá kết quả khi đổi service tồn
    // tại để ngăn.
    let release: (value: Response) => void = () => {};
    fetchMock.mockImplementation((url: string) =>
      url === "/api/invoke"
        ? new Promise<Response>((resolve) => {
            release = resolve;
          })
        : Promise.resolve(new Response(JSON.stringify({ id: "r1", latency_ms: 320 }), { status: 200 })),
    );
    const user = userEvent.setup();
    render(<Playground services={[ocrService, asrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));
    await user.selectOptions(screen.getByLabelText("Service"), "asr");

    await act(async () => {
      release(invokeOk());
    });

    expect(screen.queryByText("t1")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chạy thử" })).toBeEnabled();
  });

  it("không rò object URL khi React Strict Mode gọi effect hai lần", () => {
    // reactStrictMode đang bật trong next.config.ts. Đặt createObjectURL trong
    // updater của setState thì lần gọi thừa sinh ra một URL không ai thu hồi.
    const created: string[] = [];
    const revoked: string[] = [];
    let seq = 0;
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: vi.fn(() => {
        seq += 1;
        const url = `blob:u${seq}`;
        created.push(url);
        return url;
      }),
      revokeObjectURL: vi.fn((url: string) => revoked.push(url)),
    }));

    const { unmount } = render(
      <StrictMode>
        <Playground services={[ocrService]} hosts={hosts} />
      </StrictMode>,
    );
    fireEvent.change(screen.getByLabelText(/tệp đầu vào/i), {
      target: { files: [new File([new Uint8Array([1])], "hoadon.png", { type: "image/png" })] },
    });
    unmount();

    expect(created.length).toBeGreaterThan(0);
    expect([...revoked].sort()).toEqual([...created].sort());
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

describe("Playground — nhập bằng URL", () => {
  async function typeUrl(user: ReturnType<typeof userEvent.setup>, url: string) {
    await user.type(screen.getByLabelText(/URL đầu vào/i), url);
  }

  it("gửi input_uri thay vì file khi dán URL", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await typeUrl(user, "https://kho/anh.png");
    await user.click(screen.getByRole("button", { name: /chạy thử/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = fetchMock.mock.calls.find((c) => c[0] === "/api/invoke")?.[1].body as FormData;
    expect(body.get("input_uri")).toBe("https://kho/anh.png");
    expect(body.has("file")).toBe(false);
  });

  it("nút Chạy thử mở khoá khi chỉ có URL, không cần tệp", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    expect(screen.getByRole("button", { name: /chạy thử/i })).toBeDisabled();
    await typeUrl(user, "https://kho/anh.png");
    expect(screen.getByRole("button", { name: /chạy thử/i })).toBeEnabled();
  });

  it("chọn tệp thì xoá URL đang có — hai nguồn input loại trừ nhau", async () => {
    // Để cả hai thì request mơ hồ và /api/invoke từ chối 422. Ràng buộc phải
    // hiện ra ở UI, không để người dùng chạm vào lỗi đó mới biết.
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await typeUrl(user, "https://kho/anh.png");
    await pickFile(user);
    expect(screen.getByLabelText(/URL đầu vào/i)).toHaveValue("");
  });

  it("dán URL thì bỏ tệp đang chọn", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await typeUrl(user, "https://kho/anh.png");
    await user.click(screen.getByRole("button", { name: /chạy thử/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = fetchMock.mock.calls.find((c) => c[0] === "/api/invoke")?.[1].body as FormData;
    expect(body.has("file")).toBe(false);
    expect(body.get("input_uri")).toBe("https://kho/anh.png");
  });

  it("đổi service thì xoá URL cũ — input cũ không thuộc về service mới", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService, asrService]} hosts={hosts} />);
    await typeUrl(user, "https://kho/anh.png");
    await user.selectOptions(screen.getByLabelText("Service"), "asr");
    expect(screen.getByLabelText(/URL đầu vào/i)).toHaveValue("");
  });
});

describe("Playground — ảnh của đầu vào URL", () => {
  it("vẽ bbox lên chính ảnh ở URL, không phải lên khung trống", async () => {
    // Ca đã lọt lưới: viewer chỉ nhận được objectUrl của tệp, mà chạy bằng URL
    // thì không có tệp nào — nên imageUrl=null và OcrViewer vẽ bbox lên một ô
    // xám. Kết quả trông như model đọc được chữ từ hư không.
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await user.type(screen.getByLabelText(/URL đầu vào/i), "https://kho/anh.png");
    await user.click(screen.getByRole("button", { name: /chạy thử/i }));

    const anh = await screen.findByRole("img", { name: /ảnh đầu vào/i });
    expect(anh).toHaveAttribute("src", "https://kho/anh.png");
  });

  it("trình phát audio dùng URL khi service nhận âm thanh", async () => {
    // Cùng gốc với ca trên, nhánh audio: không có src thì nút "nghe từ" của
    // AsrViewer tua một phần tử rỗng.
    const user = userEvent.setup();
    const { container } = render(<Playground services={[asrService]} hosts={hosts} />);
    await user.type(screen.getByLabelText(/URL đầu vào/i), "https://kho/tieng.mp3");
    expect(container.querySelector("audio")).toHaveAttribute("src", "https://kho/tieng.mp3");
  });
});
