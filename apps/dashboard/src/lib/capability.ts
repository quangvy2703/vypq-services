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

/**
 * Capability output của service đã chạy một run, đọc từ chính danh sách service
 * gateway trả về.
 *
 * KHÔNG suy từ tên service: tên chỉ là nhãn người vận hành đặt trong
 * config/services.yaml, còn capability là thứ service tự khai qua /v1/info. Hai
 * cái trùng nhau hôm nay không có nghĩa là trùng mãi, và đoán sai ở đây làm
 * dashboard hiển thị output qua viewer của task khác.
 *
 * Không khớp được service nào (service đã bị gỡ khỏi cấu hình, hoặc gateway
 * chưa từng poll được nên info=null) thì trả "json" — xem thô còn hơn đoán.
 */
export function capabilityOutputFor(services: ServiceState[], serviceName: string): string {
  return services.find((state) => state.info?.name === serviceName)?.info?.capability_output ?? "json";
}
