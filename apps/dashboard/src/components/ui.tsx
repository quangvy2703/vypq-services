import type { ReactNode } from "react";

export type Tone = "ok" | "warn" | "bad" | "muted" | "brand";

const TONE_CLASS: Record<Tone, string> = {
  ok: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  warn: "bg-amber-50 text-amber-800 ring-amber-600/20",
  bad: "bg-rose-50 text-rose-700 ring-rose-600/20",
  muted: "bg-slate-100 text-slate-600 ring-slate-500/15",
  brand: "bg-brand-50 text-brand-700 ring-brand-600/20",
};

const DOT_CLASS: Record<Tone, string> = {
  ok: "bg-emerald-500",
  warn: "bg-amber-500",
  bad: "bg-rose-500",
  muted: "bg-slate-400",
  brand: "bg-brand-500",
};

export function Badge({
  tone,
  children,
  title,
  dot = false,
  mono = false,
}: {
  tone: Tone;
  children: ReactNode;
  title?: string;
  /** Chấm màu phía trước — dùng cho trạng thái, không dùng cho nhãn phân loại. */
  dot?: boolean;
  /** Nội dung là định danh máy đọc (id model, trace) chứ không phải chữ người viết. */
  mono?: boolean;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
        mono ? "font-mono tracking-tight" : ""
      } ${TONE_CLASS[tone]}`}
    >
      {dot ? (
        <span className={`size-1.5 rounded-full ${DOT_CLASS[tone]}`} />
      ) : null}
      {children}
    </span>
  );
}

export function Card({
  title,
  description,
  actions,
  flush = false,
  className = "",
  bodyClassName = "",
  children,
}: {
  title?: string;
  description?: string;
  /** Nút hoặc bộ lọc nằm bên phải tiêu đề. */
  actions?: ReactNode;
  /** Bỏ đệm trong: dùng khi nội dung là một bảng chạy hết bề ngang thẻ. */
  flush?: boolean;
  className?: string;
  /** Lớp cho riêng phần thân — cần khi thân phải giãn hết chiều cao thẻ. */
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={`overflow-hidden rounded-2xl bg-white shadow-the ring-1 ring-slate-900/[0.06] ${className}`}
    >
      {title ? (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/40 px-5 py-3.5">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold tracking-[-0.01em] text-slate-900">{title}</h2>
            {description ? <p className="mt-0.5 text-xs text-slate-500">{description}</p> : null}
          </div>
          {actions}
        </header>
      ) : null}
      <div className={`${flush ? "" : "p-5"} ${bodyClassName}`}>{children}</div>
    </section>
  );
}

/** Tiêu đề trang. Cho biết đang ở đâu mà không phải đọc thanh địa chỉ. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  /** Hành động ở cấp trang — nằm bên phải, tự xuống dòng trên màn hình hẹp. */
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pt-2 pb-1">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-[-0.02em] text-slate-900">{title}</h1>
        <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-slate-500">{description}</p>
      </div>
      {actions}
    </div>
  );
}

const BUTTON_TONE = {
  // Vạch sáng inset ở mép trên là thứ làm nút đặc trông như một khối có mặt
  // chứ không phải một hình chữ nhật tô màu.
  primary:
    "border-brand-700/60 bg-brand-600 text-white shadow-nut hover:bg-brand-700 active:bg-brand-800",
  danger: "border-slate-200 bg-white text-rose-600 hover:border-rose-200 hover:bg-rose-50",
  ghost: "border-slate-200 bg-white text-slate-700 shadow-thap hover:bg-slate-50 hover:border-slate-300",
  soft: "border-transparent bg-brand-50 text-brand-700 hover:bg-brand-100",
} as const;

// `md` cố ý cùng đệm dọc với FIELD_CLASS: nút và ô nhập rất hay đứng cạnh nhau
// trên một hàng form, lệch một bậc là chân chúng không thẳng.
const BUTTON_SIZE = {
  sm: "gap-1 rounded-lg px-2.5 py-1 text-xs",
  md: "gap-1.5 rounded-lg px-3 py-2 text-sm",
  lg: "gap-2 rounded-xl px-4 py-2.5 text-sm",
} as const;

export function Button({
  children,
  tone = "primary",
  size = "md",
  className = "",
  ...rest
}: {
  children: ReactNode;
  tone?: keyof typeof BUTTON_TONE;
  size?: keyof typeof BUTTON_SIZE;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center border font-medium transition-[background-color,border-color,box-shadow,transform] duration-150 active:translate-y-px disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none ${BUTTON_SIZE[size]} ${BUTTON_TONE[tone]} ${className}`}
    >
      {children}
    </button>
  );
}

const FIELD_CLASS =
  "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 shadow-xs transition-colors placeholder:text-slate-400 hover:border-slate-300 focus:border-brand-500 disabled:bg-slate-50 disabled:text-slate-400";

export function TextField({
  label,
  hint,
  className = "",
  ...rest
}: { label: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block space-y-1.5">
      <span className="block text-xs font-medium text-slate-600">{label}</span>
      <input {...rest} className={`${FIELD_CLASS} ${className}`} />
      {hint ? <span className="block text-xs text-slate-400">{hint}</span> : null}
    </label>
  );
}

export function SelectField({
  label,
  children,
  className = "",
  ...rest
}: { label: string; children: ReactNode } & React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    // KHÔNG thêm chữ nào khác vào trong <label> này. Tên khả truy cập của ô chọn
    // chính là phần text còn lại trong nhãn, và các truy vấn dùng nó khớp tuyệt
    // đối ("Service", /^Model$/) — một dòng gợi ý nhét vào đây là hỏng hết.
    <label className="block space-y-1.5">
      <span className="block text-xs font-medium text-slate-600">{label}</span>
      <select {...rest} className={`chon ${FIELD_CLASS} ${className}`}>
        {children}
      </select>
    </label>
  );
}

export function EmptyState({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/50 px-6 py-10 text-center">
      {icon ? (
        <div className="mx-auto mb-3 grid size-10 place-items-center rounded-xl bg-white text-slate-400 shadow-thap ring-1 ring-slate-900/5">
          {icon}
        </div>
      ) : null}
      <p className="mx-auto max-w-md text-sm leading-relaxed text-slate-500">{children}</p>
    </div>
  );
}

export function DataTable({
  headers,
  dense = false,
  children,
}: {
  headers: string[];
  /**
   * Đệm hẹp, cho bảng nằm trong một cột hẹp (viewer kết quả, panel host).
   * Đệm của tiêu đề PHẢI khớp đệm của ô thân — lệch một bậc là cả bảng lệch cột.
   */
  dense?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="cuon-manh overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200/70 bg-slate-50/70">
            {headers.map((header, index) => (
              <th
                key={header || `col-${index}`}
                scope="col"
                className={`text-[0.6875rem] font-semibold tracking-[0.06em] whitespace-nowrap text-slate-500 uppercase ${
                  dense ? "px-3 py-2" : "px-5 py-2.5"
                }`}
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}

/**
 * Dải số mô tả trên đầu một kết quả. Tách riêng khỏi bảng vì đây là thứ mắt
 * đọc trước tiên khi so hai model — nó phải to hơn và thoáng hơn phần thân.
 */
export function Stats({ items }: { items: { label: string; value: string }[] }) {
  if (items.length === 0) return null;
  return (
    <dl className="grid grid-cols-[repeat(auto-fit,minmax(7rem,1fr))] gap-px overflow-hidden rounded-xl bg-slate-200/70 ring-1 ring-slate-200/70">
      {items.map((item) => (
        <div key={item.label} className="bg-white px-3.5 py-2.5">
          <dt className="text-[0.6875rem] font-medium tracking-[0.04em] text-slate-500 uppercase">
            {item.label}
          </dt>
          <dd className="mt-0.5 text-lg font-semibold tracking-[-0.01em] text-slate-900 tabular-nums">
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Khối xám nhịp thở, giữ đúng chỗ của nội dung chưa về. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-tho rounded-lg bg-slate-200/70 ${className}`} />;
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={`size-3.5 animate-spin ${className}`}>
      <circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
      <path
        d="M8 1.75a6.25 6.25 0 0 1 6.25 6.25"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
