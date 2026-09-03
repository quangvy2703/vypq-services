"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge, Button, Card, EmptyState, SelectField, Skeleton, Spinner, Stats, TextField } from "@/components/ui";
import { ResultViewer } from "@/components/viewers/ResultViewer";
import { acceptForInput, isUsable } from "@/lib/capability";
import { formatMs } from "@/lib/format";
import { modelsForTask } from "@/lib/models";
import { summarize } from "@/lib/summary";
import type { HostState, InvokeResponse, ServiceInfo, ServiceState } from "@/lib/types";

export interface RunOutcome {
  modelLabel: string;
  invoke: InvokeResponse | null;
  latencyMs: number | null;
  error: string | null;
}

const NHAN_MAC_DINH = "(mặc định của service)";

async function messageOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { message?: string };
    return body.message ?? `lỗi ${response.status}`;
  } catch {
    return `lỗi ${response.status}`;
  }
}

/**
 * Độ trễ đọc từ bản ghi run chứ không đo bằng đồng hồ trình duyệt: số đo ở
 * trình duyệt gộp cả thời gian upload và hai chặng mạng, nên so hai model bằng
 * nó là so đường truyền chứ không phải so model.
 */
async function latencyOf(runId: string | null): Promise<number | null> {
  if (!runId) return null;
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!response.ok) return null;
    const run = (await response.json()) as { latency_ms?: number | null };
    return typeof run.latency_ms === "number" ? run.latency_ms : null;
  } catch {
    // Không lấy được độ trễ không được phép làm hỏng kết quả inference đã có.
    return null;
  }
}

/** Chạy một model. Task 10 gọi lại đúng hàm này cho từng model trong tập chọn.
 *  `nguon` là tệp đã chọn HOẶC một URL — hai thứ loại trừ nhau, xem selectFile/selectUrl. */
async function runOne(
  service: string, nguon: File | string, modelVersion: string,
): Promise<RunOutcome> {
  const body = new FormData();
  body.set("service", service);
  if (modelVersion) body.set("model_version", modelVersion);
  // Gửi input_uri thì gateway TỰ tải URL rồi mới chuyển bytes sang service;
  // dashboard không chạm vào nội dung. /api/invoke từ chối nếu có cả hai.
  if (typeof nguon === "string") body.set("input_uri", nguon);
  else body.set("file", nguon, nguon.name);
  const label = modelVersion || NHAN_MAC_DINH;
  const response = await fetch("/api/invoke", { method: "POST", body });
  if (!response.ok) {
    return { modelLabel: label, invoke: null, latencyMs: null, error: await messageOf(response) };
  }
  const invoke = (await response.json()) as InvokeResponse;
  return { modelLabel: label, invoke, latencyMs: await latencyOf(invoke.run_id), error: null };
}

/** Kích thước tệp cho người đọc. Bậc 1024 vì đây là dung lượng, không phải tốc độ. */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(0)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

/** Gọi đúng tên thứ cần thả vào, suy từ capability service tự khai. */
function danhTuDauVao(capabilityInput: string): string {
  if (capabilityInput === "image") return "ảnh";
  if (capabilityInput === "audio") return "tệp âm thanh";
  return "tệp";
}

const SVG = {
  fill: "none" as const,
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function IconTaiLen({ className = "size-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden className={className}>
      <path d="M12 15.5V3.5m0 0L8 7.5m4-4 4 4" />
      <path d="M3.5 14.5v3A3 3 0 0 0 6.5 20.5h11a3 3 0 0 0 3-3v-3" />
    </svg>
  );
}

function IconDongHo({ className = "size-3.5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden className={className}>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M12 7.25V12l3 1.75" />
    </svg>
  );
}

function IconTep({ className = "size-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden className={className}>
      <path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z" />
      <path d="M13.5 3.5V9H19" />
    </svg>
  );
}

function IconLienKet({ className = "size-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden className={className}>
      <path d="M10.5 13.5a4 4 0 0 0 5.66 0l2.6-2.6a4 4 0 1 0-5.66-5.66l-1.3 1.3" />
      <path d="M13.5 10.5a4 4 0 0 0-5.66 0l-2.6 2.6a4 4 0 1 0 5.66 5.66l1.3-1.3" />
    </svg>
  );
}

function IconCanhBao({ className = "size-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden className={className}>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M12 7.75v5M12 16.25h.01" />
    </svg>
  );
}

function IconKetQua({ className = "size-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...SVG} aria-hidden className={className}>
      <path d="M4.5 19.5h15" />
      <path d="M7.5 16V10M12 16V5.5M16.5 16v-4" />
    </svg>
  );
}

export function Playground({ services, hosts }: { services: ServiceState[]; hosts: HostState[] }) {
  // Giữ CẢ HAI tên: `key` là khoá định tuyến trong services.yaml (thứ gateway
  // tra cứu khi nhận /v1/invoke), `info.name` là tên service tự khai. Trước đây
  // chỗ này chỉ giữ info.name rồi gọi bằng nó — trùng nhau hôm nay, nhưng lệch
  // một chữ là mọi lần chạy thử trả 404 mà không ai hiểu vì sao.
  const usable = useMemo(
    () =>
      services
        .filter(isUsable)
        .map((state) => ({ key: state.name, info: state.info as ServiceInfo })),
    [services],
  );
  const [serviceName, setServiceName] = useState(usable[0]?.key ?? "");
  const service = usable.find((entry) => entry.key === serviceName) ?? usable[0];

  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [extras, setExtras] = useState<string[]>([]);
  const [outcomes, setOutcomes] = useState<RunOutcome[]>([]);
  const [pending, setPending] = useState(false);
  const [dangKeo, setDangKeo] = useState(false);
  const [anhHong, setAnhHong] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const models = useMemo(
    () => (service ? modelsForTask(hosts, service.info.task) : []),
    [hosts, service],
  );

  // Set khử trùng lặp: tick đúng model đang chọn ở ô chính thì vẫn chỉ chạy một
  // lần. Tính ở đây thay vì trong `run` để phần hiển thị đếm được sẽ có bao
  // nhiêu bảng kết quả — số khối chờ phải khớp số kết quả sắp về.
  const targets = useMemo(() => [...new Set([model, ...extras])], [model, extras]);

  // Lượt chạy đang bay. Tăng số này là tuyên bố "mọi kết quả chưa về đều lỗi
  // thời": đổi service hay đổi file xong mà kết quả cũ về trễ rồi tự hiện lên
  // thì người dùng đang nhìn output của service này qua viewer của service kia.
  const runToken = useRef(0);

  useEffect(() => {
    if (!file) {
      setObjectUrl(null);
      return;
    }
    // Tạo trong effect chứ không trong updater của setState: updater phải thuần,
    // và React Strict Mode gọi nó hai lần ở chế độ dev — URL của lần gọi bị bỏ
    // đi sẽ không bao giờ được thu hồi. Đặt ở đây thì cleanup luôn khớp một-một.
    const url = URL.createObjectURL(file);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  if (!service) {
    return (
      <EmptyState icon={<IconCanhBao className="size-5" />}>
        Chưa có service nào dùng được — kiểm tra trang Services.
      </EmptyState>
    );
  }
  // Gán lại vào biến đã có kiểu chắc chắn: TS không giữ narrowing của `service`
  // xuyên qua closure `run` bên dưới dù nó không bao giờ đổi giá trị.
  const activeService: { key: string; info: ServiceInfo } = service;

  /** Bỏ mọi lượt chạy đang bay: kết quả của chúng không còn thuộc về màn hình này. */
  function discardInFlight(): void {
    runToken.current += 1;
    setOutcomes([]);
    setPending(false);
  }

  function selectService(name: string): void {
    setServiceName(name);
    // Kết quả cũ thuộc về service cũ; giữ lại là ghép nhầm output với capability.
    discardInFlight();
    setModel("");
    // Model của service cũ không thuộc service mới — tick trùng tên là trùng hợp.
    setExtras([]);
    // Input cũ cũng vậy: một URL ảnh không phải đầu vào của service ASR.
    setUrl("");
  }

  function selectFile(next: File | null): void {
    discardInFlight();
    setFile(next);
    // Loại trừ nhau: gửi cả hai thì /api/invoke trả 422, và người dùng không
    // nên phải chạm vào lỗi đó mới biết chỉ được chọn một.
    if (next) setUrl("");
  }

  function selectUrl(next: string): void {
    discardInFlight();
    setUrl(next);
    if (next) setFile(null);
  }

  async function run(): Promise<void> {
    const nguon: File | string | null = file ?? (url.trim() || null);
    if (!nguon) return;
    const token = runToken.current + 1;
    runToken.current = token;
    setPending(true);
    const settled = await Promise.allSettled(
      targets.map((target) => runOne(activeService.key, nguon, target)),
    );
    // Vẫn phải kiểm token như lượt chạy đơn: đổi service giữa chừng rồi kết quả
    // cũ về trễ sẽ hiện output của service này qua viewer của service kia.
    if (token !== runToken.current) return;
    setOutcomes(
      settled.map((entry, index) =>
        entry.status === "fulfilled"
          ? entry.value
          : {
              modelLabel: targets[index] || NHAN_MAC_DINH,
              invoke: null,
              latencyMs: null,
              error: String(entry.reason),
            },
      ),
    );
    setPending(false);
  }

  const isImage = service.info.capability_input === "image";
  const isAudio = service.info.capability_input === "audio";
  const daCoKetQua = outcomes.length > 0;
  // URL là nguồn thật sự khi không có tệp — selectFile/selectUrl giữ cho hai
  // cái không bao giờ cùng có giá trị, nên chỉ cần kiểm theo thứ tự này.
  const dungUrl = !file && url.trim().length > 0;
  const coNguon = file !== null || dungUrl;
  /**
   * Địa chỉ trình duyệt đọc được của đầu vào — blob của tệp, hoặc chính URL
   * người dùng dán. Trước đây chỗ này chỉ có objectUrl, nên chạy bằng URL thì
   * viewer nhận imageUrl=null và vẽ bbox trên một khung xám trống.
   *
   * Dùng thẳng giá trị "sống" là an toàn: đổi tệp hay sửa URL đều đi qua
   * discardInFlight(), tức kết quả cũ bị xoá ngay — không có cửa nào để ảnh
   * của nguồn này đứng dưới bbox của nguồn kia.
   */
  const diaChiNguon = objectUrl ?? (dungUrl ? url.trim() : null);
  // Ảnh gốc đã nằm ngay trong viewer kết quả (có cả bbox chồng lên). Giữ thêm
  // một bản xem trước ở trên chỉ làm người ta cuộn nhiều hơn để so hai model.
  const xemTruocAnh = isImage && diaChiNguon !== null && !daCoKetQua;

  /** Ô nhận tệp thật. Luôn có mặt ở cả hai trạng thái — nó là nhãn "Tệp đầu vào". */
  const oNhanTep = (
    <input
      type="file"
      accept={acceptForInput(service.info.capability_input)}
      onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
      className="sr-only"
    />
  );

  const nhanKeoTha = {
    onDragEnter: (event: React.DragEvent) => {
      event.preventDefault();
      setDangKeo(true);
    },
    onDragOver: (event: React.DragEvent) => {
      // Không chặn dragover thì trình duyệt từ chối cú thả và tự mở tệp ra tab mới.
      event.preventDefault();
    },
    onDragLeave: (event: React.DragEvent) => {
      // Rê qua chữ hay icon bên trong cũng bắn dragleave. Không lọc thì viền
      // nhấp nháy suốt lúc kéo, trông như ô đang từ chối nhận tệp.
      if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
      setDangKeo(false);
    },
    onDrop: (event: React.DragEvent) => {
      event.preventDefault();
      setDangKeo(false);
      const dropped = event.dataTransfer.files?.[0];
      if (dropped) selectFile(dropped);
    },
  };

  return (
    // Cao tối thiểu bằng phần khung nhìn còn lại: khi chưa chạy gì, hai cột
    // căng hết màn hình thay vì co lại thành một mẩu thẻ trôi ở góc trên.
    <div className="grid items-start gap-5 lg:min-h-[calc(100vh-16rem)] lg:grid-cols-[20.5rem_minmax(0,1fr)]">
      {/* ── Cột trái: chạy cái gì ─────────────────────────────────────────── */}
      <div className="cuon-manh space-y-4 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:pr-1">
        <Card title="Cấu hình">
          <div className="space-y-4">
            <div className="space-y-2">
              <SelectField
                label="Service"
                value={service.key}
                onChange={(event) => selectService(event.target.value)}
              >
                {usable.map((entry) => (
                  <option key={entry.key} value={entry.key}>
                    {entry.info.name === entry.key
                      ? entry.key
                      : `${entry.key} (khai là ${entry.info.name})`}
                  </option>
                ))}
              </SelectField>
              {/* Nằm NGOÀI <label> phía trên: mọi chữ trong nhãn đều chui vào tên
                  khả truy cập của ô chọn, và tên đó phải đúng bằng "Service". */}
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone="brand">{service.info.task}</Badge>
                <Badge tone="muted" mono>
                  {service.info.capability_input} → {service.info.capability_output}
                </Badge>
              </div>
            </div>

            <SelectField
              label="Model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              <option value="">
                mặc định ({service.info.default_model ?? "service tự chọn"})
              </option>
              {models.map((option) => (
                <option key={option.id} value={option.id} disabled={!option.available}>
                  {option.id}
                  {option.kind === "finetuned" ? " · fine-tune" : ""}
                  {option.available ? "" : " · không dùng được"}
                </option>
              ))}
            </SelectField>
          </div>
        </Card>

        {models.length > 0 ? (
          <Card title="So sánh thêm với" description="Tick để chạy song song, xem cạnh nhau.">
            <fieldset>
              <legend className="sr-only">So sánh thêm với</legend>
              <div className="-my-1 flex flex-col">
                {models.map((option) => (
                  <label
                    key={option.id}
                    className={`flex items-center gap-2.5 rounded-lg px-2 py-2 transition-colors ${
                      option.available ? "cursor-pointer hover:bg-slate-50" : "cursor-not-allowed"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="tick"
                      checked={extras.includes(option.id)}
                      disabled={!option.available}
                      onChange={(event) =>
                        setExtras((current) =>
                          event.target.checked
                            ? [...current, option.id]
                            : current.filter((id) => id !== option.id),
                        )
                      }
                    />
                    <span className="min-w-0 flex-1">
                      <span
                        className={`block truncate font-mono text-[0.8125rem] tracking-tight ${
                          option.available ? "text-slate-800" : "text-slate-400"
                        }`}
                      >
                        {option.id}
                      </span>
                      <span className="block truncate text-[0.6875rem] text-slate-400">
                        {option.hostName}
                        {option.available ? "" : " · không dùng được"}
                      </span>
                    </span>
                    {option.kind === "finetuned" ? <Badge tone="warn">fine-tune</Badge> : null}
                  </label>
                ))}
              </div>
            </fieldset>
          </Card>
        ) : null}

        <div className="space-y-2">
          <Button
            type="button"
            size="lg"
            className="w-full"
            disabled={pending || (!file && !url.trim())}
            onClick={() => void run()}
          >
            {pending ? (
              <>
                <Spinner />
                Đang chạy…
              </>
            ) : (
              "Chạy thử"
            )}
          </Button>
          <p className="text-center text-xs text-slate-500">
            {!file && !url.trim()
              ? `Chọn ${danhTuDauVao(service.info.capability_input)} hoặc dán URL để chạy.`
              : targets.length > 1
                ? `${targets.length} model chạy song song trên cùng một đầu vào.`
                : "Một model, một lượt chạy."}
          </p>
        </div>
      </div>

      {/* ── Cột phải: chạy trên cái gì, và ra cái gì ──────────────────────── */}
      <div className="flex flex-col gap-5">
        <Card
          title="Đầu vào"
          description="Tải tệp lên (tối đa 25 MB) hoặc trỏ tới một URL — chọn một trong hai."
          // Chỉ giãn khi chưa có nguồn nào: lúc đó ô thả là nội dung chính của
          // cả cột. Có tệp rồi mà vẫn giãn thì bản xem trước bị kéo cao vô cớ.
          className={coNguon ? "" : "flex flex-1 flex-col"}
          bodyClassName={coNguon ? "" : "flex flex-1 flex-col"}
          actions={
            // Chỉ một nhãn, vì chỉ một nguồn chạy được. Đây là chỗ trả lời câu
            // "bấm Chạy thử bây giờ thì nó đọc cái gì".
            file ? (
              <Badge tone="brand">tệp · {formatBytes(file.size)}</Badge>
            ) : url.trim() ? (
              <Badge tone="brand">URL</Badge>
            ) : null
          }
        >
          <div className={coNguon ? "space-y-4" : "flex flex-1 flex-col gap-4"}>
          {!coNguon ? (
            <label
              {...nhanKeoTha}
              className={`flex min-h-[19rem] flex-1 cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors duration-150 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-brand-500 ${
                dangKeo
                  ? "border-brand-400 bg-brand-50"
                  : "border-slate-200 bg-slate-50/50 hover:border-brand-300 hover:bg-brand-50/40"
              }`}
            >
              {/* Nhãn của ô nhận tệp. Ẩn khỏi mắt nhưng vẫn là tên khả truy cập —
                  phần chữ nhìn thấy bên dưới nói về thao tác, không phải về ô. */}
              <span className="sr-only">Tệp đầu vào</span>
              {oNhanTep}
              <span
                className={`grid size-14 place-items-center rounded-2xl transition-colors duration-150 ${
                  dangKeo ? "bg-brand-100 text-brand-600" : "bg-white text-slate-400 shadow-thap ring-1 ring-slate-900/5"
                }`}
              >
                <IconTaiLen />
              </span>
              <span className="text-sm font-medium text-slate-700">
                {dangKeo
                  ? "Thả ra để nạp"
                  : `Kéo thả ${danhTuDauVao(service.info.capability_input)} vào đây`}
              </span>
              <span className="text-xs text-slate-500">
                hoặc bấm để chọn từ máy · nhận {acceptForInput(service.info.capability_input)}
              </span>
            </label>
          ) : (
            <div className="space-y-3">
              {xemTruocAnh ? (
                <div className="grid max-h-80 place-items-center overflow-hidden rounded-xl bg-slate-100 p-2 ring-1 ring-slate-900/[0.06] ring-inset">
                  {/* alt rỗng: bản xem trước này không mang thêm thông tin nào so
                      với dải tên ngay bên dưới, và ảnh "thật" có bbox nằm trong
                      viewer kết quả. */}
                  <img
                    src={diaChiNguon ?? ""}
                    alt=""
                    onError={() => setAnhHong(true)}
                    onLoad={() => setAnhHong(false)}
                    className={`max-h-76 w-auto rounded-lg object-contain ${anhHong ? "hidden" : ""}`}
                  />
                  {anhHong ? (
                    // URL người khác cầm có thể 404, chặn hotlink, hoặc trỏ vào
                    // thứ không phải ảnh. Nói ra, thay vì để một icon ảnh vỡ.
                    <span className="px-4 py-10 text-center text-xs text-slate-500">
                      Không tải được ảnh từ URL này để xem trước. Gateway vẫn tự tải
                      nó khi chạy, nên đây chưa chắc là lỗi.
                    </span>
                  ) : null}
                </div>
              ) : null}

              {isAudio && diaChiNguon ? (
                // Phải còn trong DOM cả khi đã có kết quả: nút "nghe từ" của
                // AsrViewer tua chính phần tử này qua ref.
                <audio ref={audioRef} src={diaChiNguon} controls className="w-full" />
              ) : null}

              <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-slate-50/60 px-3.5 py-2.5">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-white text-slate-400 shadow-thap ring-1 ring-slate-900/5">
                  {file ? <IconTep /> : <IconLienKet />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-slate-800">
                    {file ? file.name : url.trim()}
                  </span>
                  <span className="block truncate text-xs text-slate-500">
                    {file ? file.type || "không rõ kiểu" : "gateway sẽ tự tải URL này"}
                  </span>
                </span>
                <label
                  {...nhanKeoTha}
                  className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-thap transition-colors hover:border-slate-300 hover:bg-slate-50 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-brand-500"
                >
                  <span className="sr-only">Tệp đầu vào</span>
                  {oNhanTep}
                  {file ? "Đổi tệp" : "Chọn tệp"}
                </label>
              </div>
            </div>
          )}

          <div className="flex items-center gap-3">
            <span className="h-px flex-1 bg-slate-200" />
            <span className="text-xs font-medium text-slate-400">hoặc</span>
            <span className="h-px flex-1 bg-slate-200" />
          </div>

          <TextField
            label="URL đầu vào"
            type="url"
            inputMode="url"
            placeholder="https://kho/hoadon.png"
            value={url}
            onChange={(event) => selectUrl(event.target.value)}
            hint="Gateway tự tải URL này (tối đa VYPQ_MAX_DOWNLOAD_MB, mặc định 100 MB) — dashboard không chạm vào nội dung."
          />
          </div>
        </Card>

        {pending && !daCoKetQua
          ? targets.map((target, index) => (
              <div
                key={`cho-${target}-${index}`}
                className="overflow-hidden rounded-2xl bg-white shadow-the ring-1 ring-slate-900/[0.06]"
              >
                <div className="flex items-center gap-3 border-b border-slate-100 bg-slate-50/50 px-4 py-3">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="ml-auto h-6 w-20 rounded-full" />
                </div>
                <div className="space-y-3 p-4">
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-40 w-full" />
                </div>
              </div>
            ))
          : null}

        {daCoKetQua ? (
          <div className={outcomes.length > 1 ? "grid gap-5 xl:grid-cols-2" : ""}>
            {outcomes.map((entry, index) => (
              <article
                key={`${entry.modelLabel}-${index}`}
                data-testid="ket-qua"
                className="animate-hien-len overflow-hidden rounded-2xl bg-white shadow-the ring-1 ring-slate-900/[0.06]"
              >
                {/* Hàng phẳng, KHÔNG bọc nhãn model hay số ms vào thẻ con nào
                    khác: truy vấn theo text khớp cả thẻ cha lẫn thẻ con khi nội
                    dung chữ của hai cái bằng nhau, và khi đó nó báo "nhiều phần
                    tử" dù DOM không sai gì. */}
                <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-100 bg-slate-50/50 px-4 py-3">
                  <span
                    aria-hidden
                    className={`size-2 shrink-0 rounded-full ${entry.error ? "bg-rose-500" : "bg-emerald-500"}`}
                  />
                  <span className="truncate font-mono text-[0.8125rem] font-medium tracking-tight text-slate-900">
                    {entry.modelLabel}
                  </span>
                  <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-xs font-medium text-slate-600 tabular-nums ring-1 ring-slate-200 ring-inset">
                    <IconDongHo />
                    {formatMs(entry.latencyMs)}
                  </span>
                  {entry.invoke?.run_id ? (
                    <Link
                      href={`/runs/${entry.invoke.run_id}`}
                      className="rounded-md px-1.5 py-0.5 text-xs font-medium text-brand-700 transition-colors hover:bg-brand-50"
                    >
                      Xem run
                    </Link>
                  ) : null}
                  {entry.invoke ? (
                    <span className="ma text-slate-400" title="trace_id">
                      {entry.invoke.trace_id}
                    </span>
                  ) : null}
                </header>

                <div className="space-y-4 p-4">
                  {entry.error ? (
                    <div
                      role="alert"
                      className="flex items-start gap-2.5 rounded-xl bg-rose-50 px-3.5 py-3 text-sm text-rose-700 ring-1 ring-rose-600/15 ring-inset"
                    >
                      <IconCanhBao className="mt-0.5 size-4 shrink-0" />
                      <span className="min-w-0">{entry.error}</span>
                    </div>
                  ) : (
                    <>
                      <Stats
                        items={summarize(
                          service.info.capability_output,
                          entry.invoke?.result ?? null,
                        )}
                      />
                      <ResultViewer
                        capabilityOutput={service.info.capability_output}
                        output={entry.invoke?.result ?? null}
                        imageUrl={isImage ? diaChiNguon : null}
                        audioUrl={isAudio ? diaChiNguon : null}
                        onSeek={(seconds) => {
                          if (audioRef.current) audioRef.current.currentTime = seconds;
                        }}
                      />
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : null}

        {!pending && !daCoKetQua && file ? (
          <EmptyState icon={<IconKetQua />}>
            Bấm <span className="font-medium text-slate-700">Chạy thử</span> để xem model đọc ra gì.
            Tick thêm model ở cột bên trái để so kết quả cạnh nhau trên cùng tệp này.
          </EmptyState>
        ) : null}
      </div>
    </div>
  );
}
