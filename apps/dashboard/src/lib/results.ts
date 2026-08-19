import type { AsrResult, OcrResult, Polygon, Segment, TextBox } from "@/lib/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toPolygon(value: unknown): Polygon | null {
  if (!Array.isArray(value) || value.length < 4) return null;
  const points: Polygon = [];
  for (const point of value) {
    if (!Array.isArray(point) || point.length < 2) return null;
    const [x, y] = point;
    if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) {
      return null;
    }
    points.push([x, y]);
  }
  return points;
}

function toTextBox(value: unknown, index: number): TextBox | null {
  if (!isRecord(value)) return null;
  const polygon = toPolygon(value.polygon);
  if (!polygon) return null;
  return {
    id: typeof value.id === "number" ? value.id : index,
    polygon,
    text: typeof value.text === "string" ? value.text : "",
    confidence: typeof value.confidence === "number" ? value.confidence : null,
    ignore: value.ignore === true,
  };
}

/**
 * Đọc `RunRecord.output` — thứ gateway lưu nguyên si từ service. Service là code
 * của mình nhưng model-host thì có thể là bản mới hơn, nên payload lệch hợp đồng
 * phải rơi về `null` để ResultViewer hiện JSON thô, thay vì làm trang trắng.
 */
export function asOcrResult(output: unknown): OcrResult | null {
  if (!isRecord(output)) return null;
  if (!Array.isArray(output.boxes)) return null;
  const boxes = output.boxes.map(toTextBox).filter((box): box is TextBox => box !== null);
  return { full_text: typeof output.full_text === "string" ? output.full_text : "", boxes };
}

function toSegment(value: unknown): Segment | null {
  if (!isRecord(value)) return null;
  const { start, end } = value;
  if (typeof start !== "number" || typeof end !== "number") return null;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return {
    start,
    end,
    text: typeof value.text === "string" ? value.text : "",
    speaker: typeof value.speaker === "string" ? value.speaker : null,
  };
}

export function asAsrResult(output: unknown): AsrResult | null {
  if (!isRecord(output)) return null;
  if (!Array.isArray(output.segments)) return null;
  const segments = output.segments.map(toSegment).filter((seg): seg is Segment => seg !== null);
  return { text: typeof output.text === "string" ? output.text : "", segments };
}

/**
 * `polygon` chỉ cần đọc x,y theo vị trí — không cần đúng hẳn kiểu tuple
 * `Polygon` của `TextBox`. Nới kiểu tham số theo cấu trúc (thay vì đòi
 * `TextBox[]` cứng) để chấp nhận cả literal `number[][]` mà TS suy ra khi một
 * biến polygon được khai báo rồi mới spread — như trong test — mà không phải
 * ép kiểu `as Polygon` ở phía gọi.
 */
interface BoxLike {
  polygon: readonly (readonly number[])[];
}

/**
 * Khung toạ độ dùng khi KHÔNG có ảnh gốc (mọi run sync đều ghi input_uri=null).
 * Tối thiểu 1×1: svg viewBox có chiều bằng 0 thì không vẽ ra gì cả.
 */
export function boundingExtent(boxes: readonly BoxLike[]): { width: number; height: number } {
  let width = 1;
  let height = 1;
  for (const box of boxes) {
    for (const point of box.polygon) {
      const x = point[0];
      const y = point[1];
      if (typeof x === "number" && x > width) width = x;
      if (typeof y === "number" && y > height) height = y;
    }
  }
  return { width, height };
}
