"use client";

import { DataTable, EmptyState } from "@/components/ui";
import { formatClock } from "@/lib/format";
import type { AsrResult } from "@/lib/types";

function IconNghe() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden className="size-3">
      <path d="M8 5.5v13a.75.75 0 0 0 1.14.64l10.5-6.5a.75.75 0 0 0 0-1.28l-10.5-6.5A.75.75 0 0 0 8 5.5" />
    </svg>
  );
}

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
      <div className="rounded-xl border border-slate-200 bg-slate-50/60 px-4 py-3.5">
        <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-800">{result.text}</p>
      </div>
      {result.segments.length === 0 ? null : (
        <div className="overflow-hidden rounded-xl ring-1 ring-slate-900/[0.06] ring-inset">
          <DataTable dense headers={["Thời gian", "Người nói", "Nội dung", ""]}>
            {result.segments.map((segment, index) => (
              <tr key={`${segment.start}-${index}`} className="transition-colors hover:bg-slate-50">
                {/* Ba node text rời nằm thẳng trong ô, không bọc thêm thẻ nào:
                    mốc thời gian được tra bằng đúng chuỗi ghép của chúng. */}
                <td className="px-3 py-2 font-mono text-xs whitespace-nowrap text-slate-500 tabular-nums">
                  {formatClock(segment.start)} → {formatClock(segment.end)}
                </td>
                <td className="px-3 py-2">
                  {segment.speaker ? (
                    <span className="inline-flex items-center rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600">
                      {segment.speaker}
                    </span>
                  ) : (
                    <span className="text-xs text-slate-400">—</span>
                  )}
                </td>
                <td className="px-3 py-2 text-sm text-slate-800">{segment.text}</td>
                <td className="px-3 py-2 text-right">
                  {audioUrl ? (
                    <button
                      type="button"
                      aria-label={`Nghe từ ${formatClock(segment.start)}`}
                      onClick={() => onSeek(segment.start)}
                      className="inline-grid size-7 place-items-center rounded-full text-slate-400 transition-colors hover:bg-brand-50 hover:text-brand-600"
                    >
                      <IconNghe />
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </DataTable>
        </div>
      )}
    </div>
  );
}
