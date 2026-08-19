import { viewerFor } from "@/lib/capability";
import { formatClock } from "@/lib/format";
import { asAsrResult, asOcrResult } from "@/lib/results";

export interface Stat {
  label: string;
  value: string;
}

/**
 * Thống kê MÔ TẢ, không phải điểm số: không có ground truth thì "nhiều box hơn"
 * không đồng nghĩa "tốt hơn". Chấm điểm (CER/WER/IoU) là việc của Plan C.
 */
export function summarize(
  capabilityOutput: string,
  output: Record<string, unknown> | null,
): Stat[] {
  if (output === null) return [];
  const kind = viewerFor(capabilityOutput);

  if (kind === "text_boxes") {
    const parsed = asOcrResult(output);
    if (!parsed) return [];
    const kept = parsed.boxes.filter((box) => !box.ignore);
    const scored = kept.filter((box) => box.confidence !== null);
    const average =
      scored.length === 0
        ? "—"
        : (scored.reduce((sum, box) => sum + (box.confidence ?? 0), 0) / scored.length).toFixed(2);
    return [
      { label: "Số vùng chữ", value: String(kept.length) },
      { label: "Số ký tự", value: String(parsed.full_text.length) },
      { label: "Độ tin cậy TB", value: average },
    ];
  }

  if (kind === "transcript") {
    const parsed = asAsrResult(output);
    if (!parsed) return [];
    const end = parsed.segments.reduce((max, segment) => Math.max(max, segment.end), 0);
    return [
      { label: "Số segment", value: String(parsed.segments.length) },
      { label: "Thời lượng", value: formatClock(end) },
      { label: "Số ký tự", value: String(parsed.text.length) },
    ];
  }

  return [];
}
