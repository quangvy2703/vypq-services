export interface RunsFilters {
  service?: string;
  status?: string;
  trace_id?: string;
  limit: number;
}

export function buildRunsHref(filters: RunsFilters, offset: number): string {
  const params = new URLSearchParams();
  if (filters.trace_id) params.set("trace_id", filters.trace_id);
  if (filters.service) params.set("service", filters.service);
  if (filters.status) params.set("status", filters.status);
  params.set("limit", String(filters.limit));
  // offset=0 là mặc định; để nó trong URL làm link trang đầu khác nhau tuỳ đường
  // vào, và bookmark trông rối mà không thêm thông tin gì.
  if (offset > 0) params.set("offset", String(offset));
  return `/runs?${params.toString()}`;
}
