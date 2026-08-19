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
}: {
  tone: Tone;
  children: ReactNode;
  title?: string;
  /** Chấm màu phía trước — dùng cho trạng thái, không dùng cho nhãn phân loại. */
  dot?: boolean;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE_CLASS[tone]}`}
    >
      {dot ? <span className={`size-1.5 rounded-full ${DOT_CLASS[tone]}`} /> : null}
      {children}
    </span>
  );
}

export function Card({
  title,
  description,
  actions,
  flush = false,
  children,
}: {
  title?: string;
  description?: string;
  /** Nút hoặc bộ lọc nằm bên phải tiêu đề. */
  actions?: ReactNode;
  /** Bỏ đệm trong: dùng khi nội dung là một bảng chạy hết bề ngang thẻ. */
  flush?: boolean;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-900/5">
      {title ? (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
            {description ? <p className="mt-0.5 text-xs text-slate-500">{description}</p> : null}
          </div>
          {actions}
        </header>
      ) : null}
      <div className={flush ? "" : "p-5"}>{children}</div>
    </section>
  );
}

/** Tiêu đề trang. Cho biết đang ở đâu mà không phải đọc thanh địa chỉ. */
export function PageHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-1">
      <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
      <p className="mt-1 text-sm text-slate-500">{description}</p>
    </div>
  );
}

const BUTTON_TONE = {
  primary:
    "bg-brand-600 text-white shadow-sm hover:bg-brand-700 active:bg-brand-700 border-transparent",
  danger: "border-slate-200 bg-white text-rose-600 hover:border-rose-200 hover:bg-rose-50",
  ghost: "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
} as const;

export function Button({
  children,
  tone = "primary",
  className = "",
  ...rest
}: {
  children: ReactNode;
  tone?: keyof typeof BUTTON_TONE;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${BUTTON_TONE[tone]} ${className}`}
    >
      {children}
    </button>
  );
}

const FIELD_CLASS =
  "w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-xs transition-colors placeholder:text-slate-400 hover:border-slate-300 focus:border-brand-500";

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
    <label className="block space-y-1.5">
      <span className="block text-xs font-medium text-slate-600">{label}</span>
      <select {...rest} className={`${FIELD_CLASS} ${className}`}>
        {children}
      </select>
    </label>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-6 py-10 text-center">
      <p className="mx-auto max-w-md text-sm text-slate-500">{children}</p>
    </div>
  );
}

export function DataTable({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <div className="cuon-manh overflow-x-auto">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-slate-100 bg-slate-50/70">
            {headers.map((header, index) => (
              <th
                key={header || `col-${index}`}
                scope="col"
                className="px-5 py-2.5 text-xs font-semibold tracking-wide whitespace-nowrap text-slate-500 uppercase"
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
