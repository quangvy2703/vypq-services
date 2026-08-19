import Link from "next/link";

import { Badge, Button, Card, DataTable, EmptyState, SelectField, TextField } from "@/components/ui";
import { formatMs, formatTimestamp } from "@/lib/format";
import { buildRunsHref, type RunsFilters } from "@/lib/pagination";
import type { RunRecord, RunStatus } from "@/lib/types";

const STATUS_TONE = { ok: "ok", pending: "warn", failed: "bad" } as const;

function StatusBadge({ status }: { status: RunStatus }) {
  return <Badge dot tone={STATUS_TONE[status]}>{status}</Badge>;
}

function PageLink({ href, children }: { href: string | null; children: string }) {
  if (href === null) {
    return <span className="rounded border border-slate-200 px-3 py-1 text-sm text-slate-300">{children}</span>;
  }
  return (
    <Link href={href} className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100">
      {children}
    </Link>
  );
}

export function RunsTable({
  runs,
  total,
  offset,
  filters,
}: {
  runs: RunRecord[];
  total: number;
  offset: number;
  filters: RunsFilters;
}) {
  const previous = offset > 0 ? buildRunsHref(filters, Math.max(0, offset - filters.limit)) : null;
  const hasMore = offset + runs.length < total;
  const next = hasMore ? buildRunsHref(filters, offset + filters.limit) : null;

  return (
    <div className="space-y-4">
      <Card title="Lọc">
        <form method="get" className="grid gap-4 md:grid-cols-[repeat(3,minmax(0,1fr))_auto] md:items-end">
          <TextField name="service" label="Service" defaultValue={filters.service ?? ""} placeholder="ocr" />
          <SelectField name="status" label="Trạng thái" defaultValue={filters.status ?? ""}>
            <option value="">tất cả</option>
            <option value="ok">ok</option>
            <option value="failed">failed</option>
            <option value="pending">pending</option>
          </SelectField>
          <TextField name="trace_id" label="Trace ID" defaultValue={filters.trace_id ?? ""} placeholder="52df9a2c…" />
          <input type="hidden" name="limit" value={filters.limit} />
          <Button type="submit">Lọc</Button>
        </form>
      </Card>

      <Card flush>
        {runs.length === 0 ? (
          <div className="p-5"><EmptyState>Không có run nào khớp bộ lọc.</EmptyState></div>
        ) : (
          <DataTable headers={["Thời điểm", "Service", "Model", "Mode", "Trạng thái", "Độ trễ", "Trace", ""]}>
            {runs.map((run) => (
              <tr key={run.id}>
                <td className="whitespace-nowrap px-5 py-3 text-xs text-slate-600">{formatTimestamp(run.created_at)}</td>
                <td className="px-5 py-3">{run.service}</td>
                <td className="px-5 py-3 text-xs">{run.model_version ?? "—"}</td>
                <td className="px-5 py-3 text-xs">{run.mode}</td>
                <td className="px-5 py-3">
                  <StatusBadge status={run.status} />
                  {run.error ? <div className="mt-1 max-w-[22rem] truncate text-xs text-rose-600/90" title={run.error}>{run.error}</div> : null}
                </td>
                <td className="px-5 py-3 text-xs">{formatMs(run.latency_ms)}</td>
                <td className="px-5 py-3 text-xs">
                  {/* Bấm trace_id ra mọi run cùng trace — đó là cách nhìn shadow-run:
                      một event, nhiều model version, mỗi cái một dòng. */}
                  <Link href={buildRunsHref({ trace_id: run.trace_id, limit: filters.limit }, 0)} className="ma text-brand-700 hover:underline" title={run.trace_id}>
                    {run.trace_id.length > 12 ? `${run.trace_id.slice(0, 12)}…` : run.trace_id}
                  </Link>
                </td>
                <td className="px-5 py-3 text-right text-xs whitespace-nowrap">
                  <Link href={`/runs/${run.id}`} className="underline">
                    {/* Mỗi dòng đều có link "Chi tiết" giống hệt nhau về mặt chữ —
                        với người dùng trình đọc màn hình, nghe lặp lại "Chi tiết"
                        nhiều lần không phân biệt được dòng nào ứng với run nào.
                        Thêm id vào tên truy cập (ẩn khỏi mắt) để link tự mô tả. */}
                    <span className="sr-only">Run {run.id}: </span>
                    Chi tiết
                  </Link>
                </td>
              </tr>
            ))}
          </DataTable>
        )}
        <div className="flex items-center gap-3 border-t border-slate-100 px-5 py-3">
          <PageLink href={previous}>Trước</PageLink>
          <PageLink href={next}>Sau</PageLink>
          <span className="text-xs text-slate-500">
            {runs.length === 0 ? "0 / 0" : `${offset + 1}–${offset + runs.length} / ${total}`}
          </span>
        </div>
      </Card>
    </div>
  );
}
