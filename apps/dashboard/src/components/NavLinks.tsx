"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/hosts", label: "Model Hosts" },
  { href: "/services", label: "Services" },
  { href: "/playground", label: "Playground" },
  { href: "/runs", label: "Lịch sử" },
];

export function NavLinks() {
  const pathname = usePathname();

  return (
    <nav className="flex items-center gap-1">
      {LINKS.map((link) => {
        // startsWith để /runs/<id> vẫn tô sáng mục "Lịch sử". Không dùng khớp
        // chính xác, nếu không mở trang chi tiết là mất dấu vị trí hiện tại.
        const dangO = pathname === link.href || pathname.startsWith(`${link.href}/`);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={dangO ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              dangO
                ? "bg-brand-50 text-brand-700"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            }`}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
