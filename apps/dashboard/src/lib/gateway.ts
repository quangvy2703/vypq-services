import "server-only";

import { getServerEnv } from "@/lib/env";
import { GatewayError } from "@/lib/errors";
import type {
  HostRegistration,
  HostState,
  HostsResponse,
  InvokeResponse,
  RunRecord,
  RunsQuery,
  RunsResponse,
  ServicesResponse,
} from "@/lib/types";

async function toGatewayError(response: Response): Promise<GatewayError> {
  // Gateway trả ErrorResponse {code, message, trace_id} cho lỗi của nó, nhưng
  // một proxy/ingress đứng giữa có thể trả HTML — vẫn phải ra GatewayError chứ
  // không được ném SyntaxError từ .json().
  let code = "internal";
  let message = `gateway trả ${response.status}`;
  let traceId: string | null = null;
  try {
    const body = (await response.json()) as { code?: string; message?: string; trace_id?: string | null };
    if (typeof body.code === "string") code = body.code;
    if (typeof body.message === "string") message = body.message;
    if (typeof body.trace_id === "string") traceId = body.trace_id;
  } catch {
    // Giữ nguyên message mặc định.
  }
  return new GatewayError(response.status, code, message, traceId);
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const env = getServerEnv();
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${env.gatewayToken}`);
  const response = await fetch(`${env.gatewayUrl}${path}`, {
    ...init,
    headers,
    // Trạng thái host và danh sách run đổi liên tục; một bản cache 30 giây ở đây
    // nghĩa là người vận hành nhìn thấy host đã chết vẫn xanh.
    cache: "no-store",
  });
  if (!response.ok) throw await toGatewayError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function runsQueryString(query: RunsQuery): string {
  const params = new URLSearchParams();
  if (query.trace_id) params.set("trace_id", query.trace_id);
  if (query.service) params.set("service", query.service);
  if (query.status) params.set("status", query.status);
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.offset !== undefined) params.set("offset", String(query.offset));
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export const gateway = {
  listHosts(): Promise<HostsResponse> {
    return call<HostsResponse>("/v1/hosts");
  },

  registerHost(registration: HostRegistration): Promise<HostState> {
    return call<HostState>("/v1/hosts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(registration),
    });
  },

  deleteHost(name: string): Promise<void> {
    // encodeURIComponent: tên host do người dùng gõ, có thể chứa "/" và làm
    // request rơi vào route khác.
    return call<void>(`/v1/hosts/${encodeURIComponent(name)}`, { method: "DELETE" });
  },

  listServices(): Promise<ServicesResponse> {
    return call<ServicesResponse>("/v1/services");
  },

  invokeUpload(service: string, file: File, modelVersion: string | null): Promise<InvokeResponse> {
    const form = new FormData();
    form.set("service", service);
    // Gửi chuỗi rỗng thì gateway coi là đã chọn model tên "" và bỏ qua
    // default_model của service — phải không set field mới đúng.
    if (modelVersion) form.set("model_version", modelVersion);
    form.set("file", file, file.name);
    // Cố tình KHÔNG đặt content-type: fetch phải tự sinh boundary của multipart.
    return call<InvokeResponse>("/v1/invoke/upload", { method: "POST", body: form });
  },

  listRuns(query: RunsQuery): Promise<RunsResponse> {
    return call<RunsResponse>(`/v1/runs${runsQueryString(query)}`);
  },

  getRun(runId: string): Promise<RunRecord> {
    return call<RunRecord>(`/v1/runs/${encodeURIComponent(runId)}`);
  },
};
