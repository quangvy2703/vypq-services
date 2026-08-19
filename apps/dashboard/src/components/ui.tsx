import type { ReactNode } from "react";

export type Tone = "ok" | "warn" | "bad" | "muted";

const TONE_CLASS: Record<Tone, string> = {
  ok: "bg-emerald-100 text-emerald-800",
  warn: "bg-amber-100 text-amber-800",
  bad: "bg-red-100 text-red-800",
  muted: "bg-slate-100 text-slate-600",
};

export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${TONE_CLASS[tone]}`}>
      {children}
    </span>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {title ? <h2 className="mb-3 text-sm font-semibold text-slate-700">{title}</h2> : null}
      {children}
    </section>
  );
}

export function Button({
  children, tone = "primary", ...rest
}: { children: ReactNode; tone?: "primary" | "danger" } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const base = tone === "danger" ? "border-red-300 text-red-700 hover:bg-red-50" : "bg-slate-900 text-white hover:bg-slate-700";
  return (
    <button {...rest} className={`rounded border px-3 py-1.5 text-sm disabled:opacity-40 ${base}`}>
      {children}
    </button>
  );
}

export function TextField({
  label, ...rest
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block space-y-1">
      <span className="text-sm text-slate-600">{label}</span>
      <input {...rest} className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm" />
    </label>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="rounded border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">{children}</p>;
}

export function DataTable({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-slate-500">
          <tr>
            {headers.map((header) => (
              <th key={header} className="px-3 py-2 font-medium">{header}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}
