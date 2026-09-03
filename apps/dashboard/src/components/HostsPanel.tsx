"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { RelativeTime } from "@/components/RelativeTime";
import { Badge, Button, Card, DataTable, EmptyState, TextField } from "@/components/ui";
import type { HostState, ModelInfo } from "@/lib/types";

async function messageOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { message?: string };
    return body.message ?? `lỗi ${response.status}`;
  } catch {
    return `lỗi ${response.status}`;
  }
}

function ModelChip({ model }: { model: ModelInfo }) {
  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      <Badge
        tone={model.available ? (model.kind === "finetuned" ? "warn" : "muted") : "bad"}
        title={model.available ? `${model.kind} · ${model.runner}` : "không dùng được trên host này"}
      >
        {model.id}
      </Badge>
      {/* Nhãn kind phải là text hiển thị, không chỉ nằm trong title: người
          dùng lướt mắt qua bảng cần phân biệt fine-tune/open-source ngay,
          không phải rê chuột vào từng chip mới thấy. */}
      <span className="text-[10px] uppercase tracking-wide text-slate-400">{model.kind}</span>
    </span>
  );
}

export function HostsPanel({ hosts }: { hosts: HostState[] }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function register(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setPending(true);
    setError(null);
    const response = await fetch("/api/hosts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, url, token }),
    });
    setPending(false);
    if (!response.ok) {
      setError(await messageOf(response));
      return;
    }
    setName("");
    setUrl("");
    setToken("");
    // Trang là Server Component; refresh() bắt server lấy lại danh sách host.
    router.refresh();
  }

  async function remove(hostName: string): Promise<void> {
    // Gỡ host = mọi service mất một đường định tuyến ngay lập tức. Đắt hơn
    // nhiều so với gõ lại, nên hỏi trước.
    if (!confirm(`Gỡ host "${hostName}"? Các service sẽ ngừng định tuyến vào máy này.`)) return;
    const response = await fetch(`/api/hosts/${encodeURIComponent(hostName)}`, { method: "DELETE" });
    if (!response.ok) {
      setError(await messageOf(response));
      return;
    }
    router.refresh();
  }

  return (
    <div className="space-y-6">
      <Card title="Cắm một máy GPU vừa thuê">
        <form onSubmit={register} className="grid gap-4 md:grid-cols-[repeat(3,minmax(0,1fr))_auto] md:items-end">
          <TextField label="Tên" value={name} onChange={(e) => setName(e.target.value)} placeholder="a100-vast" />
          <TextField label="URL" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://abc.ngrok.app" />
          <TextField label="Token" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="VYPQ_MODEL_HOST_TOKEN" />
          <Button type="submit" disabled={pending || !name.trim() || !url.trim()}>
            {pending ? "Đang cắm…" : "Cắm host"}
          </Button>
        </form>
        {error ? <p role="alert" className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-600/15 ring-inset">{error}</p> : null}
        <p className="mt-4 text-xs text-slate-500">
          Gateway poll mỗi 15 giây và coi host là chết sau 45 giây không phản hồi — host mới cắm cần khoảng một chu kỳ để chuyển xanh.
        </p>
      </Card>

      <Card title="Host đang có" flush>
        {hosts.length === 0 ? (
          <div className="p-5"><EmptyState>Chưa cắm máy GPU nào. Thuê máy, chạy model-host, mở ngrok rồi dán URL vào ô trên.</EmptyState></div>
        ) : (
          <DataTable headers={["Host", "Trạng thái", "Model", "Thấy lần cuối", ""]} dense>
            {hosts.map((host) => (
              <tr key={host.name}>
                <td className="px-3 py-2 align-top">
                  <div className="font-medium">{host.name}</div>
                  <div className="ma mt-0.5 text-slate-500">{host.url}</div>
                </td>
                <td className="px-3 py-2 align-top">
                  <Badge dot tone={host.healthy ? "ok" : "bad"}>{host.healthy ? "khoẻ" : "chết"}</Badge>
                  {host.last_error ? <div className="mt-1.5 max-w-xs text-xs text-rose-600">{host.last_error}</div> : null}
                </td>
                <td className="px-3 py-2 align-top">
                  {host.models.length === 0 ? (
                    <span className="text-xs text-slate-400">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {host.models.map((model) => <ModelChip key={model.id} model={model} />)}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 align-top text-xs text-slate-600"><RelativeTime iso={host.last_seen_at} /></td>
                <td className="px-3 py-2 align-top">
                  <Button tone="danger" type="button" aria-label={`Gỡ ${host.name}`} onClick={() => void remove(host.name)}>
                    Gỡ
                  </Button>
                </td>
              </tr>
            ))}
          </DataTable>
        )}
      </Card>
    </div>
  );
}
