"use client";

import { DataTable, EmptyState } from "@/components/ui";
import { formatClock } from "@/lib/format";
import type { AsrResult } from "@/lib/types";

/**
 * `onSeek` do component cha cung cấp thay vì tự giữ ref tới <audio>: playground
 * sở hữu phần tử audio (nó cũng sở hữu object URL của file), còn trang lịch sử
 * không có audio nào để tua.
 */
export function AsrViewer({
  result,
  audioUrl,
  onSeek,
}: {
  result: AsrResult;
  audioUrl: string | null;
  onSeek: (seconds: number) => void;
}) {
  if (result.segments.length === 0 && result.text.length === 0) {
    return <EmptyState>Model không nhận ra lời nào trong file này.</EmptyState>;
  }

  return (
    <div className="space-y-3">
      <div className="rounded border border-slate-200 bg-white p-3">
        <p className="whitespace-pre-wrap text-sm">{result.text}</p>
      </div>
      {result.segments.length === 0 ? null : (
        <DataTable headers={["Thời gian", "Người nói", "Nội dung", ""]}>
          {result.segments.map((segment, index) => (
            <tr key={`${segment.start}-${index}`}>
              <td className="whitespace-nowrap px-3 py-1.5 text-xs text-slate-600">
                {formatClock(segment.start)} → {formatClock(segment.end)}
              </td>
              <td className="px-3 py-1.5 text-xs">{segment.speaker ?? "—"}</td>
              <td className="px-3 py-1.5">{segment.text}</td>
              <td className="px-3 py-1.5">
                {audioUrl ? (
                  <button
                    type="button"
                    aria-label={`Nghe từ ${formatClock(segment.start)}`}
                    onClick={() => onSeek(segment.start)}
                    className="text-xs text-slate-500 hover:text-slate-900"
                  >
                    ▶
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </DataTable>
      )}
    </div>
  );
}
