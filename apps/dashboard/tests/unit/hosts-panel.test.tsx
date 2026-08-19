import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HostsPanel } from "@/components/HostsPanel";
import type { HostState } from "@/lib/types";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh, push: vi.fn(), replace: vi.fn() }) }));

const healthy: HostState = {
  name: "a100-vast",
  url: "https://abc.ngrok.app",
  healthy: true,
  models: [
    { id: "paddleocr-v4-vi", task: "ocr", kind: "opensource", runner: "paddle", loaded: true, available: true, vram_mb: 1200, base: null, trained_on: null },
    { id: "vietocr-ft-invoice", task: "ocr", kind: "finetuned", runner: "vietocr", loaded: false, available: false, vram_mb: 0, base: "vietocr-base", trained_on: "invoice-vi-v2" },
  ],
  last_seen_at: "2026-08-19T06:59:50Z",
  last_error: null,
};

const broken: HostState = {
  name: "may-cu",
  url: "https://cu.ngrok.app",
  healthy: false,
  models: [],
  last_seen_at: null,
  last_error: "ConnectTimeout sau 5s",
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  refresh.mockClear();
  fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HostsPanel", () => {
  it("hiện host khoẻ kèm model và thời điểm thấy lần cuối", () => {
    render(<HostsPanel hosts={[healthy]} />);
    const row = screen.getByRole("row", { name: /a100-vast/ });
    expect(within(row).getByText("khoẻ")).toBeInTheDocument();
    expect(within(row).getByText("paddleocr-v4-vi")).toBeInTheDocument();
  });

  it("đánh dấu model không dùng được thay vì giấu đi", () => {
    // Model thiếu checkpoint hay hết VRAM vẫn nằm trong /v1/models với
    // available=false; giấu nó đi thì người dùng không hiểu vì sao chọn không ra.
    render(<HostsPanel hosts={[healthy]} />);
    expect(screen.getByTitle(/không dùng được/)).toHaveTextContent("vietocr-ft-invoice");
  });

  it("phân biệt model fine-tune với model open-source", () => {
    render(<HostsPanel hosts={[healthy]} />);
    expect(screen.getByText("finetuned")).toBeInTheDocument();
  });

  it("hiện lỗi lần poll gần nhất của host đang chết", () => {
    render(<HostsPanel hosts={[broken]} />);
    const row = screen.getByRole("row", { name: /may-cu/ });
    expect(within(row).getByText("chết")).toBeInTheDocument();
    expect(within(row).getByText(/ConnectTimeout sau 5s/)).toBeInTheDocument();
  });

  it("nói rõ host mới đăng ký chưa từng được poll", () => {
    render(<HostsPanel hosts={[broken]} />);
    expect(screen.getByText("chưa từng")).toBeInTheDocument();
  });

  it("hiện hướng dẫn khi chưa có host nào", () => {
    render(<HostsPanel hosts={[]} />);
    expect(screen.getByText(/chưa cắm máy GPU nào/i)).toBeInTheDocument();
  });

  it("đăng ký host mới rồi làm mới dữ liệu trang", async () => {
    const user = userEvent.setup();
    render(<HostsPanel hosts={[]} />);
    await user.type(screen.getByLabelText("Tên"), "a100-vast");
    await user.type(screen.getByLabelText("URL"), "https://abc.ngrok.app");
    await user.type(screen.getByLabelText("Token"), "bi-mat");
    await user.click(screen.getByRole("button", { name: "Cắm host" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/hosts");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      name: "a100-vast", url: "https://abc.ngrok.app", token: "bi-mat",
    });
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  });

  it("hiện thông điệp lỗi của server thay vì im lặng", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ code: "bad_input", message: "URL phải là http hoặc https, không phải ftp:" }), { status: 422 }),
    );
    const user = userEvent.setup();
    render(<HostsPanel hosts={[]} />);
    await user.type(screen.getByLabelText("Tên"), "x");
    await user.type(screen.getByLabelText("URL"), "ftp://x");
    await user.click(screen.getByRole("button", { name: "Cắm host" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/URL phải là http hoặc https/);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("hỏi lại trước khi gỡ host — gỡ nhầm là cắt định tuyến của mọi service", async () => {
    const confirmSpy = vi.fn().mockReturnValue(false);
    vi.stubGlobal("confirm", confirmSpy);
    const user = userEvent.setup();
    render(<HostsPanel hosts={[healthy]} />);
    await user.click(screen.getByRole("button", { name: /gỡ a100-vast/i }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("gỡ host khi người dùng xác nhận", async () => {
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    const user = userEvent.setup();
    render(<HostsPanel hosts={[healthy]} />);
    await user.click(screen.getByRole("button", { name: /gỡ a100-vast/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/hosts/a100-vast");
    expect(init.method).toBe("DELETE");
  });
});
