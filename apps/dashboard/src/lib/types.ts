/**
 * Bản chép tay của `packages/vypq-contracts` sang TypeScript. Giữ đúng tên
 * field snake_case như JSON gateway trả về — đổi sang camelCase ở đây sẽ tạo
 * một tầng dịch phải bảo trì hai chiều.
 */

export type Task = "ocr" | "asr";
export type ModelKind = "opensource" | "finetuned";
export type HealthStatus = "ok" | "degraded" | "down";
export type InvokeMode = "sync" | "async";
export type RunStatus = "pending" | "ok" | "failed";

export interface ModelInfo {
  id: string;
  task: Task;
  kind: ModelKind;
  runner: string;
  loaded: boolean;
  available: boolean;
  vram_mb: number;
  base: string | null;
  trained_on: string | null;
}

export interface HostRegistration {
  name: string;
  url: string;
  token: string | null;
}

/** KHÔNG có `token`: /v1/hosts cố tình không trả token của máy GPU. */
export interface HostState {
  name: string;
  url: string;
  healthy: boolean;
  models: ModelInfo[];
  last_seen_at: string | null;
  last_error: string | null;
}

export interface HostsResponse {
  hosts: HostState[];
}

export interface ServiceInfo {
  name: string;
  task: Task;
  capability_input: string;
  capability_output: string;
  version: string;
  invoke_path: string;
  default_model: string | null;
}

export interface ServiceState {
  /** null = gateway chưa từng poll thành công. Không được đoán task. */
  info: ServiceInfo | null;
  base_url: string;
  status: HealthStatus;
  last_seen_at: string | null;
}

export interface ServicesResponse {
  services: ServiceState[];
}

export interface InvokeResponse {
  trace_id: string;
  mode: InvokeMode;
  run_id: string | null;
  result: Record<string, unknown> | null;
}

export interface RunRecord {
  id: string;
  trace_id: string;
  service: string;
  model_version: string | null;
  mode: InvokeMode;
  status: RunStatus;
  input_uri: string | null;
  output: Record<string, unknown> | null;
  latency_ms: number | null;
  error: string | null;
  created_at: string;
}

export interface RunsResponse {
  runs: RunRecord[];
  total: number;
}

export interface RunsQuery {
  trace_id?: string;
  service?: string;
  status?: RunStatus;
  limit?: number;
  offset?: number;
}

export type Polygon = [number, number][];

export interface TextBox {
  id: number;
  polygon: Polygon;
  text: string;
  confidence: number | null;
  ignore: boolean;
}

export interface OcrResult {
  full_text: string;
  boxes: TextBox[];
}

export interface Segment {
  start: number;
  end: number;
  text: string;
  speaker: string | null;
}

export interface AsrResult {
  text: string;
  segments: Segment[];
}
