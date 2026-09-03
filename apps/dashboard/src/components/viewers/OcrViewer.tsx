"use client";

import { useCallback, useState } from "react";

import { DataTable, EmptyState } from "@/components/ui";
import { boundingExtent } from "@/lib/results";
import type { OcrResult } from "@/lib/types";

function pointsOf(polygon: [number, number][]): string {
  return polygon.map(([x, y]) => `${x},${y}`).join(" ");
}

/** Dưới ngưỡng này thì con số đáng để mắt dừng lại, nên nó đổi màu. */
const NGUONG_THAP = 0.75;

export function OcrViewer({
  result,
  imageUrl,
}: {
  result: OcrResult;
  imageUrl: string | null;
}) {
  // Kích thước thật của ảnh chỉ biết sau khi trình duyệt tải xong. Trước đó,
  // và trong mọi trường hợp không có ảnh, dùng khung suy từ chính các polygon.
  //
  // Số đo được GẮN KÈM src đã đo, chứ không dọn bằng một effect chạy theo
  // imageUrl. Dọn bằng effect là một cuộc đua có thật và ta đã thua nó: ảnh
  // nằm sẵn trong cache (playground vừa tải đúng URL đó cho khung xem trước)
  // thì `load` bắn xong TRƯỚC khi effect mount kịp chạy, và effect xoá luôn số
  // đo vừa ghi. Sau đó không còn sự kiện nào nữa, `natural` ở lại null, khung
  // toạ độ rơi về boundingExtent — nhỏ hơn ảnh thật — và mọi bbox lệch chỗ.
  const [natural, setNatural] = useState<{
    src: string;
    width: number;
    height: number;
  } | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [loiTai, setLoiTai] = useState<string | null>(null);

  /**
   * Đo qua CẢ ref lẫn onLoad, vì hai đường bù cho nhau: ref bắt ca ảnh đã
   * complete ngay lúc gắn vào DOM (load không bắn lại nữa), onLoad bắt mọi lần
   * đổi src sau đó. Dependency rỗng để danh tính ref đứng yên — ref inline đổi
   * danh tính mỗi lần render, mà mỗi lần gọi lại setState một object mới là một
   * vòng render vô tận.
   */
  const ghiSoDo = useCallback((node: HTMLImageElement | null) => {
    // naturalWidth > 0 đã là tín hiệu đủ và đúng cho cả hai đường: ảnh chưa tải
    // xong luôn báo 0, ảnh đã có trong cache báo số thật ngay lúc gắn vào DOM.
    if (!node || !node.naturalWidth) return;
    const src = node.getAttribute("src") ?? "";
    setNatural((truoc) =>
      truoc && truoc.src === src && truoc.width === node.naturalWidth
        ? truoc
        : { src, width: node.naturalWidth, height: node.naturalHeight },
    );
  }, []);

  // Chỉ tin số đo khi nó đo đúng tấm ảnh đang hiển thị.
  const soDo = natural !== null && natural.src === imageUrl ? natural : null;
  const anhHong = loiTai !== null && loiTai === imageUrl;
  const frame = soDo ?? boundingExtent(result.boxes);

  return (
    <div className="@container">
      <div className="grid gap-4 @2xl:grid-cols-2">
        <div className="relative w-full self-start overflow-hidden rounded-xl bg-slate-100 ring-1 ring-slate-900/[0.06] ring-inset">
          {imageUrl && !anhHong ? (
            <img
              ref={ghiSoDo}
              src={imageUrl}
              alt="Ảnh đầu vào"
              className="block h-auto w-full"
              onError={() => setLoiTai(imageUrl)}
              onLoad={(event) => ghiSoDo(event.currentTarget)}
            />
          ) : (
            // Không có ảnh, hoặc có mà tải không nổi (URL 404, chặn hotlink):
            // giữ đúng tỉ lệ khung toạ độ để bố cục các box vẫn đọc được. Bỏ
            // khối này thì <img> hỏng co về cao 0, kéo luôn lớp svg phủ tuyệt
            // đối lên nó xuống 0 — mất sạch bbox.
            <div
              style={{
                paddingBottom: `${(frame.height / frame.width) * 100}%`,
              }}
            />
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
                className={`transition-[fill,stroke] duration-150 ${
                  selected === box.id
                    ? "fill-amber-400/30 stroke-amber-500"
                    : box.ignore
                      ? "fill-none stroke-slate-400/70"
                      : "fill-emerald-400/10 stroke-emerald-500"
                }`}
                // Box bị bỏ qua vẽ nét đứt: khác biệt vẫn đọc được cả khi in đen
                // trắng hay khi người dùng không phân biệt được màu.
                strokeDasharray={box.ignore ? "4 3" : undefined}
                // vectorEffect: nét vẫn 1px sau khi svg co giãn theo khung ảnh.
                vectorEffect="non-scaling-stroke"
                strokeWidth={selected === box.id ? 2.5 : 1.5}
              />
            ))}
          </svg>
        </div>

        <div className="space-y-3">
          {result.boxes.length === 0 ? (
            <EmptyState>Model không tìm thấy chữ nào trong ảnh này.</EmptyState>
          ) : (
            <div className="overflow-hidden rounded-xl ring-1 ring-slate-900/[0.06] ring-inset">
              <DataTable dense headers={["#", "Text", "Độ tin cậy"]}>
                {result.boxes.map((box) => (
                  <tr
                    key={box.id}
                    data-ignored={box.ignore}
                    onMouseEnter={() => setSelected(box.id)}
                    onMouseLeave={() => setSelected(null)}
                    className={`transition-colors ${
                      box.ignore
                        ? "text-slate-400 hover:bg-slate-50"
                        : "cursor-default hover:bg-amber-50/70"
                    }`}
                  >
                    <td className="px-3 py-1.5 text-xs text-slate-400 tabular-nums">
                      {box.id}
                    </td>
                    <td className="px-3 py-1.5">{box.text}</td>
                    <td className="px-3 py-1.5">
                      <span
                        className={`font-mono text-xs tabular-nums ${
                          box.confidence !== null &&
                          box.confidence < NGUONG_THAP
                            ? "text-amber-600"
                            : "text-slate-500"
                        }`}
                      >
                        {box.confidence === null
                          ? "—"
                          : box.confidence.toFixed(2)}
                      </span>
                    </td>
                  </tr>
                ))}
              </DataTable>
            </div>
          )}
          <details className="group overflow-hidden rounded-xl border border-slate-200 bg-white">
            <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 [&::-webkit-details-marker]:hidden">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={1.75}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
                className="size-4 shrink-0 text-slate-400 transition-transform duration-150 group-open:rotate-90"
              >
                <path d="M9.5 6.5 15 12l-5.5 5.5" />
              </svg>
              Toàn văn
            </summary>
            {/* Một khối text liền, không tách theo từ: đây là thứ người ta bôi đen
              rồi copy. Truy vấn test phải khoanh vùng vào khối này thay vì bắt
              sản phẩm tự cắt nhỏ ra cho dễ tìm. */}
            <pre className="cuon-manh overflow-x-auto border-t border-slate-100 bg-slate-50/60 px-3.5 py-3 text-sm leading-relaxed whitespace-pre-wrap text-slate-700">
              {result.full_text}
            </pre>
          </details>
        </div>
      </div>
    </div>
  );
}
