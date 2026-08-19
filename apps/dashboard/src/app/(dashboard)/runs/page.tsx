import { PageHeader } from "@/components/ui";
import { RunsTable } from "@/components/RunsTable";
import { gateway } from "@/lib/gateway";
import type { RunsFilters } from "@/lib/pagination";
import type { RunStatus, RunsQuery } from "@/lib/types";

export const dynamic = "force-dynamic";

const STATUSES: readonly string[] = ["pending", "ok", "failed"];

function one(value: string | string[] | undefined): string | undefined {
  const first = Array.isArray(value) ? value[0] : value;
  return first?.trim() || undefined;
}

function clamp(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const status = one(params.status);
  const filters: RunsFilters = {
    service: one(params.service),
    // Bỏ status lạ thay vì đẩy xuống gateway: một URL cũ bị bookmark không nên
    // biến thành trang lỗi.
    status: status && STATUSES.includes(status) ? status : undefined,
    trace_id: one(params.trace_id),
    limit: clamp(one(params.limit), 50, 1, 200),
  };
  const offset = clamp(one(params.offset), 0, 0, Number.MAX_SAFE_INTEGER);

  const query: RunsQuery = { limit: filters.limit, offset };
  if (filters.service) query.service = filters.service;
  if (filters.trace_id) query.trace_id = filters.trace_id;
  if (filters.status) query.status = filters.status as RunStatus;

  const { runs, total } = await gateway.listRuns(query);
  return (
    <>
      <PageHeader
        title="Lịch sử chạy"
        description="Mọi lần gọi model đều được ghi lại. Bấm trace để xem mọi run cùng một yêu cầu."
      />
      <RunsTable runs={runs} total={total} offset={offset} filters={filters} />
    </>
  );
}
