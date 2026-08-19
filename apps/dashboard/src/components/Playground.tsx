"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge, Button, Card, EmptyState } from "@/components/ui";
import { ResultViewer } from "@/components/viewers/ResultViewer";
import { acceptForInput, isUsable } from "@/lib/capability";
import { modelsForTask } from "@/lib/models";
import type { HostState, InvokeResponse, ServiceInfo, ServiceState } from "@/lib/types";

export interface RunOutcome {
  modelLabel: string;
  invoke: InvokeResponse | null;
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

/** Chạy một model. Task 10 gọi lại đúng hàm này cho từng model trong tập chọn. */
async function runOne(service: string, file: File, modelVersion: string): Promise<RunOutcome> {
  const body = new FormData();
  body.set("service", service);
  if (modelVersion) body.set("model_version", modelVersion);
  body.set("file", file, file.name);
  const response = await fetch("/api/invoke", { method: "POST", body });
  const label = modelVersion || "(mặc định của service)";
  if (!response.ok) return { modelLabel: label, invoke: null, error: await messageOf(response) };
  return { modelLabel: label, invoke: (await response.json()) as InvokeResponse, error: null };
}

export function Playground({ services, hosts }: { services: ServiceState[]; hosts: HostState[] }) {
  const usable = useMemo(
    () => services.filter(isUsable).map((state) => state.info as ServiceInfo),
    [services],
  );
  const [serviceName, setServiceName] = useState(usable[0]?.name ?? "");
  const service = usable.find((info) => info.name === serviceName) ?? usable[0];

  const [file, setFile] = useState<File | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [outcome, setOutcome] = useState<RunOutcome | null>(null);
  const [pending, setPending] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const models = useMemo(
    () => (service ? modelsForTask(hosts, service.task) : []),
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
  const activeService: ServiceInfo = service;

  /** Bỏ mọi lượt chạy đang bay: kết quả của chúng không còn thuộc về màn hình này. */
  function discardInFlight(): void {
    runToken.current += 1;
    setOutcome(null);
    setPending(false);
  }

  function selectService(name: string): void {
    setServiceName(name);
    // Kết quả cũ thuộc về service cũ; giữ lại là ghép nhầm output với capability.
    discardInFlight();
    setModel("");
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
    const result = await runOne(activeService.name, file, model);
    // Lượt này đã bị bỏ trong lúc chờ. Không đụng vào state: lượt mới (nếu có)
    // tự quản pending của nó, còn discardInFlight đã dọn sạch phần hiển thị.
    if (token !== runToken.current) return;
    setOutcome(result);
    setPending(false);
  }

  const isImage = service.capability_input === "image";
  const isAudio = service.capability_input === "audio";

  return (
    <div className="space-y-6">
      <Card title="Chạy thử">
        <div className="grid gap-3 md:grid-cols-4 md:items-end">
          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Service</span>
            <select
              value={service.name}
              onChange={(event) => selectService(event.target.value)}
              className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
            >
              {usable.map((info) => (
                <option key={info.name} value={info.name}>{info.name}</option>
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
              <option value="">mặc định ({service.default_model ?? "service tự chọn"})</option>
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
              accept={acceptForInput(service.capability_input)}
              onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
              className="w-full text-sm"
            />
          </label>

          <Button type="button" disabled={pending || !file} onClick={() => void run()}>
            {pending ? "Đang chạy…" : "Chạy thử"}
          </Button>
        </div>
        <p className="mt-3 text-xs text-slate-500">Tệp tối đa 25 MB, khớp giới hạn inline của service.</p>
      </Card>

      {isAudio && objectUrl ? (
        <audio ref={audioRef} src={objectUrl} controls className="w-full" />
      ) : null}

      {outcome ? (
        <Card title={`Kết quả · ${outcome.modelLabel}`}>
          {outcome.error ? (
            <p role="alert" className="text-sm text-red-600">{outcome.error}</p>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
                <span>trace_id</span>
                <Badge tone="muted">{outcome.invoke?.trace_id}</Badge>
                {outcome.invoke?.run_id ? (
                  <Link href={`/runs/${outcome.invoke.run_id}`} className="underline">Xem run</Link>
                ) : null}
              </div>
              <ResultViewer
                capabilityOutput={service.capability_output}
                output={outcome.invoke?.result ?? null}
                imageUrl={isImage ? objectUrl : null}
                audioUrl={isAudio ? objectUrl : null}
                onSeek={(seconds) => {
                  if (audioRef.current) audioRef.current.currentTime = seconds;
                }}
              />
            </div>
          )}
        </Card>
      ) : null}
    </div>
  );
}
