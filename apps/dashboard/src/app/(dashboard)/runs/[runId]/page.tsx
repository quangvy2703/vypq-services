import Link from "next/link";
import { notFound } from "next/navigation";

import { Badge, Card } from "@/components/ui";
import { ResultViewer } from "@/components/viewers/ResultViewer";
import { GatewayError } from "@/lib/errors";
import { capabilityOutputFor } from "@/lib/capability";
import { formatMs, formatTimestamp } from "@/lib/format";
import { gateway } from "@/lib/gateway";
import type { RunRecord } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function RunDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  let run: RunRecord;
  try {
    run = await gateway.getRun(runId);
  } catch (error) {
    if (error instanceof GatewayError && error.status === 404) notFound();
    throw error;
  }
  const { services } = await gateway.listServices();

  return (
    <div className="space-y-4">
      <Card title={`Run ${run.id}`}>
        <dl className="grid gap-x-6 gap-y-2 text-sm md:grid-cols-4">
          <div><dt className="text-xs text-slate-500">Service</dt><dd>{run.service}</dd></div>
          <div><dt className="text-xs text-slate-500">Model</dt><dd>{run.model_version ?? "—"}</dd></div>
          <div><dt className="text-xs text-slate-500">Mode</dt><dd>{run.mode}</dd></div>
          <div><dt className="text-xs text-slate-500">Trạng thái</dt><dd><Badge tone={run.status === "ok" ? "ok" : run.status === "pending" ? "warn" : "bad"}>{run.status}</Badge></dd></div>
          <div><dt className="text-xs text-slate-500">Độ trễ</dt><dd>{formatMs(run.latency_ms)}</dd></div>
          <div><dt className="text-xs text-slate-500">Thời điểm</dt><dd>{formatTimestamp(run.created_at)}</dd></div>
          <div className="md:col-span-2">
            <dt className="text-xs text-slate-500">Trace</dt>
            <dd><Link href={`/runs?trace_id=${encodeURIComponent(run.trace_id)}&limit=50`} className="underline">{run.trace_id}</Link></dd>
          </div>
          <div className="md:col-span-4">
            <dt className="text-xs text-slate-500">Input</dt>
            {/* Run sync ghi input_uri=null (SyncProxy.invoke) — chỉ run async đi
                qua Kafka mới có URI. Nói thẳng ra thay vì để ô trống khó hiểu. */}
            <dd className="text-xs">{run.input_uri ?? "không lưu (chạy sync, file gửi trực tiếp)"}</dd>
          </div>
        </dl>
        {run.error ? <p role="alert" className="mt-3 rounded bg-red-50 p-3 text-sm text-red-700">{run.error}</p> : null}
      </Card>

      <Card title="Kết quả">
        <ResultViewer
          capabilityOutput={capabilityOutputFor(services, run.service)}
          output={run.output}
          imageUrl={null}
          audioUrl={null}
        />
      </Card>
    </div>
  );
}
