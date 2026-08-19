"use client";

import { AsrViewer } from "@/components/viewers/AsrViewer";
import { OcrViewer } from "@/components/viewers/OcrViewer";
import { EmptyState } from "@/components/ui";
import { viewerFor } from "@/lib/capability";
import { asAsrResult, asOcrResult } from "@/lib/results";

function RawJson({ output }: { output: unknown }) {
  return (
    <pre className="overflow-x-auto rounded border border-slate-200 bg-white p-3 text-xs">
      {JSON.stringify(output, null, 2)}
    </pre>
  );
}

export function ResultViewer({
  capabilityOutput,
  output,
  imageUrl,
  audioUrl,
  onSeek,
}: {
  capabilityOutput: string;
  output: Record<string, unknown> | null;
  imageUrl: string | null;
  audioUrl: string | null;
  onSeek?: (seconds: number) => void;
}) {
  if (output === null) {
    return <EmptyState>Chưa có kết quả — run đang chờ hoặc đã lỗi.</EmptyState>;
  }

  const kind = viewerFor(capabilityOutput);
  if (kind === "text_boxes") {
    const parsed = asOcrResult(output);
    // Không parse được thì hiện thô: capability khai một đằng, service trả một
    // nẻo vẫn phải xem được, nếu không thì đúng lúc cần chẩn đoán lại mất dữ liệu.
    if (parsed) return <OcrViewer result={parsed} imageUrl={imageUrl} />;
  }
  if (kind === "transcript") {
    const parsed = asAsrResult(output);
    if (parsed) return <AsrViewer result={parsed} audioUrl={audioUrl} onSeek={onSeek ?? (() => {})} />;
  }
  return <RawJson output={output} />;
}
