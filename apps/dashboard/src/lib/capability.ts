import type { Tone } from "@/components/ui";
import type { HealthStatus, ServiceState } from "@/lib/types";

export type ViewerKind = "text_boxes" | "transcript" | "json";

/**
 * Đây là NƠI DUY NHẤT dashboard suy ra hành vi từ capability của service.
 * Spec §3.8: thêm service NER/TTS chỉ cần trả đúng /v1/info — nên mọi nhánh
 * không nhận ra đều phải có đường đi tiếp, không được ném.
 */
export function acceptForInput(capabilityInput: string): string {
  if (capabilityInput === "image") return "image/*";
  if (capabilityInput === "audio") return "audio/*";
  return "*/*";
}

export function viewerFor(capabilityOutput: string): ViewerKind {
  if (capabilityOutput === "text_boxes") return "text_boxes";
  if (capabilityOutput === "transcript") return "transcript";
  return "json";
}

/** Dùng được = đã biết cách gọi (info != null) và chưa bị coi là chết. */
export function isUsable(state: ServiceState): boolean {
  return state.info !== null && state.status !== "down";
}

export function statusTone(status: HealthStatus): Tone {
  if (status === "ok") return "ok";
  if (status === "degraded") return "warn";
  return "bad";
}
