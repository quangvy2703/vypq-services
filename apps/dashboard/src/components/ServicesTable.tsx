import { Badge, Card, DataTable, EmptyState } from "@/components/ui";
import { statusTone } from "@/lib/capability";
import { formatTimestamp } from "@/lib/format";
import type { ServiceState } from "@/lib/types";

const STATUS_LABEL = { ok: "khoẻ", degraded: "chập chờn", down: "chết" } as const;

export function ServicesTable({ services }: { services: ServiceState[] }) {
  return (
    <Card title="Service đang đăng ký">
      {services.length === 0 ? (
        <EmptyState>Gateway chưa khai service nào — kiểm tra `config/services.yaml`.</EmptyState>
      ) : (
        <DataTable headers={["Service", "Task", "Capability", "Model mặc định", "Trạng thái", "Thấy lần cuối"]}>
          {services.map((state) => (
            <tr key={state.base_url}>
              <td className="px-3 py-2 align-top">
                {/* name và task thường trùng chữ (vd "ocr"/"ocr"): gộp version
                    vào cùng một text node với name để không tạo ra hai node DOM
                    riêng biệt cùng mang đúng chữ "ocr" — vừa rối mắt, vừa khiến
                    truy vấn theo text (kể cả của người dùng dùng trình đọc màn
                    hình) không phân biệt được đây là ô nào. */}
                <div className="font-medium">
                  {state.info ? `${state.info.name} · v${state.info.version}` : "—"}
                </div>
                <div className="text-xs text-slate-500">{state.base_url}</div>
                {state.info ? <div className="text-xs text-slate-400">{state.info.invoke_path}</div> : null}
              </td>
              {state.info === null ? (
                // Một ô gộp thay vì rải "—": gateway chưa từng poll được service
                // này nên KHÔNG có gì để điền, và đoán vào đây là nói dối.
                <td className="px-3 py-2 align-top text-xs text-slate-500" colSpan={3}>
                  Chưa liên hệ được — gateway chưa đọc được /v1/info lần nào
                </td>
              ) : (
                <>
                  <td className="px-3 py-2 align-top">{state.info.task}</td>
                  <td className="px-3 py-2 align-top text-xs text-slate-600">
                    {state.info.capability_input} → {state.info.capability_output}
                  </td>
                  <td className="px-3 py-2 align-top text-xs">{state.info.default_model ?? "—"}</td>
                </>
              )}
              <td className="px-3 py-2 align-top">
                <Badge tone={statusTone(state.status)}>{STATUS_LABEL[state.status]}</Badge>
              </td>
              <td className="px-3 py-2 align-top text-xs text-slate-600">{formatTimestamp(state.last_seen_at)}</td>
            </tr>
          ))}
        </DataTable>
      )}
    </Card>
  );
}
