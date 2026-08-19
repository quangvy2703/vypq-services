"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge, Button, Card, EmptyState } from "@/components/ui";
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

/** Chạy một model. Task 10 gọi lại đúng hàm này cho từng model trong tập chọn. */
async function runOne(service: string, file: File, modelVersion: string): Promise<RunOutcome> {
  const body = new FormData();
  body.set("service", service);
  if (modelVersion) body.set("model_version", modelVersion);
  body.set("file", file, file.name);
  const label = modelVersion || "(mặc định của service)";
  const response = await fetch("/api/invoke", { method: "POST", body });
  if (!response.ok) {
    return { modelLabel: label, invoke: null, latencyMs: null, error: await messageOf(response) };
  }
  const invoke = (await response.json()) as InvokeResponse;
  return { modelLabel: label, invoke, latencyMs: await latencyOf(invoke.run_id), error: null };
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
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [extras, setExtras] = useState<string[]>([]);
  const [outcomes, setOutcomes] = useState<RunOutcome[]>([]);
  const [pending, setPending] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const models = useMemo(
    () => (service ? modelsForTask(hosts, service.info.task) : []),
    [hosts, service],
  );

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
    return <EmptyState>Chưa có service nào dùng được — kiểm tra trang Services.</EmptyState>;
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
  }

  function selectFile(next: File | null): void {
    discardInFlight();
    setFile(next);
  }

  async function run(): Promise<void> {
    if (!file) return;
    const token = runToken.current + 1;
    runToken.current = token;
    setPending(true);
    // Set khử trùng lặp: tick đúng model đang chọn ở ô chính thì vẫn chỉ chạy một lần.
    const targets = [...new Set([model, ...extras])];
    const settled = await Promise.allSettled(
      targets.map((target) => runOne(activeService.key, file, target)),
    );
    // Vẫn phải kiểm token như lượt chạy đơn: đổi service giữa chừng rồi kết quả
    // cũ về trễ sẽ hiện output của service này qua viewer của service kia.
    if (token !== runToken.current) return;
    setOutcomes(
      settled.map((entry, index) =>
        entry.status === "fulfilled"
          ? entry.value
          : {
              modelLabel: targets[index] || "(mặc định của service)",
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

  return (
    <div className="space-y-6">
      <Card title="Chạy thử">
        <div className="grid gap-3 md:grid-cols-4 md:items-end">
          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Service</span>
            <select
              value={service.key}
              onChange={(event) => selectService(event.target.value)}
              className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
            >
              {usable.map((entry) => (
                <option key={entry.key} value={entry.key}>
                  {entry.info.name === entry.key ? entry.key : `${entry.key} (khai là ${entry.info.name})`}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Model</span>
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
            >
              <option value="">mặc định ({service.info.default_model ?? "service tự chọn"})</option>
              {models.map((option) => (
                <option key={option.id} value={option.id} disabled={!option.available}>
                  {option.id}{option.kind === "finetuned" ? " · fine-tune" : ""}{option.available ? "" : " · không dùng được"}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Tệp đầu vào</span>
            <input
              type="file"
              accept={acceptForInput(service.info.capability_input)}
              onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
              className="w-full text-sm"
            />
          </label>

          <Button type="button" disabled={pending || !file} onClick={() => void run()}>
            {pending ? "Đang chạy…" : "Chạy thử"}
          </Button>
        </div>
        <p className="mt-3 text-xs text-slate-500">Tệp tối đa 25 MB, khớp giới hạn inline của service.</p>

        {models.length > 0 ? (
          <fieldset className="mt-4 border-t border-slate-100 pt-3">
            <legend className="text-xs text-slate-500">So sánh thêm với</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {models.map((option) => (
                <label key={option.id} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
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
                  <span>{option.id}</span>
                  {option.kind === "finetuned" ? <Badge tone="warn">fine-tune</Badge> : null}
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}
      </Card>

      {isAudio && objectUrl ? (
        <audio ref={audioRef} src={objectUrl} controls className="w-full" />
      ) : null}

      {outcomes.length > 0 ? (
        <div className={outcomes.length > 1 ? "grid gap-4 xl:grid-cols-2" : ""}>
          {outcomes.map((entry, index) => (
            <div key={`${entry.modelLabel}-${index}`} data-testid="ket-qua">
              <Card title="Kết quả">
                <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-slate-600">
                  <Badge tone="muted">{entry.modelLabel}</Badge>
                  <span>{formatMs(entry.latencyMs)}</span>
                  {entry.invoke?.run_id ? (
                    <Link href={`/runs/${entry.invoke.run_id}`} className="underline">Xem run</Link>
                  ) : null}
                  {entry.invoke ? <span>{entry.invoke.trace_id}</span> : null}
                </div>
                {entry.error ? (
                  <p role="alert" className="text-sm text-red-600">{entry.error}</p>
                ) : (
                  <div className="space-y-3">
                    <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
                      {summarize(service.info.capability_output, entry.invoke?.result ?? null).map((stat) => (
                        <div key={stat.label} className="flex gap-1.5">
                          <dt className="text-slate-500">{stat.label}</dt>
                          <dd className="font-medium">{stat.value}</dd>
                        </div>
                      ))}
                    </dl>
                    <ResultViewer
                      capabilityOutput={service.info.capability_output}
                      output={entry.invoke?.result ?? null}
                      imageUrl={isImage ? objectUrl : null}
                      audioUrl={isAudio ? objectUrl : null}
                      onSeek={(seconds) => {
                        if (audioRef.current) audioRef.current.currentTime = seconds;
                      }}
                    />
                  </div>
                )}
              </Card>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
