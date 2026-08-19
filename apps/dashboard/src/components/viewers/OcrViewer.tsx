"use client";

import { useState } from "react";

import { DataTable, EmptyState } from "@/components/ui";
import { boundingExtent } from "@/lib/results";
import type { OcrResult } from "@/lib/types";

function pointsOf(polygon: [number, number][]): string {
  return polygon.map(([x, y]) => `${x},${y}`).join(" ");
}

export function OcrViewer({ result, imageUrl }: { result: OcrResult; imageUrl: string | null }) {
  // Kích thước thật của ảnh chỉ biết sau khi trình duyệt tải xong. Trước đó,
  // và trong mọi trường hợp không có ảnh, dùng khung suy từ chính các polygon.
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const frame = natural ?? boundingExtent(result.boxes);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="relative w-full self-start overflow-hidden rounded border border-slate-200 bg-white">
        {imageUrl ? (
          <img
            src={imageUrl}
            alt="Ảnh đầu vào"
            className="block h-auto w-full"
            onLoad={(event) =>
              setNatural({
                width: event.currentTarget.naturalWidth || 1,
                height: event.currentTarget.naturalHeight || 1,
              })
            }
          />
        ) : (
          // Không có ảnh (mọi run sync ghi input_uri=null): giữ đúng tỉ lệ khung
          // toạ độ để bố cục các box vẫn đọc được.
          <div style={{ paddingBottom: `${(frame.height / frame.width) * 100}%` }} />
        )}
        <svg
          viewBox={`0 0 ${frame.width} ${frame.height}`}
          className="absolute inset-0 h-full w-full"
          aria-label="Vùng chữ model tìm được"
        >
          {result.boxes.map((box) => (
            <polygon
              key={box.id}
              points={pointsOf(box.polygon)}
              data-selected={selected === box.id}
              className={
                selected === box.id
                  ? "fill-amber-400/30 stroke-amber-600"
                  : box.ignore
                    ? "fill-none stroke-slate-400"
                    : "fill-emerald-400/10 stroke-emerald-600"
              }
              // vectorEffect: nét vẫn 1px sau khi svg co giãn theo khung ảnh.
              vectorEffect="non-scaling-stroke"
              strokeWidth={1.5}
            />
          ))}
        </svg>
      </div>

      <div className="space-y-3">
        {result.boxes.length === 0 ? (
          <EmptyState>Model không tìm thấy chữ nào trong ảnh này.</EmptyState>
        ) : (
          <DataTable headers={["#", "Text", "Độ tin cậy"]}>
            {result.boxes.map((box) => (
              <tr
                key={box.id}
                data-ignored={box.ignore}
                onMouseEnter={() => setSelected(box.id)}
                onMouseLeave={() => setSelected(null)}
                className={box.ignore ? "text-slate-400" : "cursor-default hover:bg-amber-50"}
              >
                <td className="px-3 py-1.5">{box.id}</td>
                <td className="px-3 py-1.5">{box.text}</td>
                <td className="px-3 py-1.5 text-xs">{box.confidence === null ? "—" : box.confidence.toFixed(2)}</td>
              </tr>
            ))}
          </DataTable>
        )}
        <details className="rounded border border-slate-200 bg-white p-3">
          <summary className="cursor-pointer text-sm text-slate-600">Toàn văn</summary>
          {/* Một khối text liền, không tách theo từ: đây là thứ người ta bôi đen
              rồi copy. Truy vấn test phải khoanh vùng vào khối này thay vì bắt
              sản phẩm tự cắt nhỏ ra cho dễ tìm. */}
          <pre className="mt-2 whitespace-pre-wrap text-sm">{result.full_text}</pre>
        </details>
      </div>
    </div>
  );
}
