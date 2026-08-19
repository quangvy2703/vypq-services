import type { HostState, ModelKind, Task } from "@/lib/types";

export interface ModelOption {
  id: string;
  kind: ModelKind;
  hostName: string;
  available: boolean;
}

/**
 * Lọc theo task giống hệt cách service tự lọc (spec §3.3): một model-host phục
 * vụ nhiều service, và service ocr chỉ được thấy model task=ocr.
 */
export function modelsForTask(hosts: HostState[], task: Task): ModelOption[] {
  const byId = new Map<string, ModelOption>();
  for (const host of hosts) {
    // Host chết thì model của nó không định tuyến tới đâu được.
    if (!host.healthy) continue;
    for (const model of host.models) {
      if (model.task !== task) continue;
      const existing = byId.get(model.id);
      // Cùng id trên nhiều máy thuê: giữ bản đang dùng được, vì đó là bản sẽ
      // thật sự chạy khi service chọn host.
      if (existing && (existing.available || !model.available)) continue;
      byId.set(model.id, {
        id: model.id,
        kind: model.kind,
        hostName: host.name,
        available: model.available,
      });
    }
  }
  return [...byId.values()].sort((a, b) => a.id.localeCompare(b.id));
}
