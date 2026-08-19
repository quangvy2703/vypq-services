import type { NextResponse } from "next/server";

import { gateway } from "@/lib/gateway";
import { respond } from "@/lib/route-helpers";
import type { RunStatus, RunsQuery } from "@/lib/types";

const STATUSES: readonly RunStatus[] = ["pending", "ok", "failed"];

/**
 * Giữ đúng khoảng gateway chấp nhận (limit 1..200, offset ≥ 0).
 *
 * Không tham số bị lệch với tham số rỗng: `Number(null)` và `Number("")` đều
 * ra `0`, một số hữu hạn — nếu đưa thẳng vào `Number()` thì trang không có
 * `?limit=` sẽ bị kẹp thành 1 thay vì dùng mặc định 50. Phải chặn hai trường
 * hợp "không có giá trị" trước khi ép kiểu số.
 */
function clamp(raw: string | null, fallback: number, min: number, max: number): number {
  if (raw === null || raw.trim() === "") return fallback;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

export function GET(request: Request): Promise<NextResponse> {
  return respond(() => {
    const params = new URL(request.url).searchParams;
    const query: RunsQuery = {
      limit: clamp(params.get("limit"), 50, 1, 200),
      offset: clamp(params.get("offset"), 0, 0, Number.MAX_SAFE_INTEGER),
    };
    const traceId = params.get("trace_id")?.trim();
    const service = params.get("service")?.trim();
    const status = params.get("status")?.trim();
    if (traceId) query.trace_id = traceId;
    if (service) query.service = service;
    // Lọc ở đây chứ không đẩy xuống: gateway trả 422 cho status lạ, và một
    // đường dẫn cũ bị bookmark sẽ biến thành trang lỗi thay vì danh sách.
    if (status && (STATUSES as readonly string[]).includes(status)) {
      query.status = status as RunStatus;
    }
    return gateway.listRuns(query);
  });
}
