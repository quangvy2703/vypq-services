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
    // Rãnh chìm bọc quanh cả nhóm: mục đang mở là một phiến trắng nổi lên trong
    // rãnh đó. Chỉ tô nền mục đang mở như trước thì ba mục còn lại trôi tự do
    // trên nền trắng của thanh nav và không nhóm lại thành một bộ.
    <nav className="flex items-center gap-0.5 rounded-xl bg-slate-100/80 p-1 ring-1 ring-slate-900/[0.04] ring-inset">
      {LINKS.map((link) => {
        // startsWith để /runs/<id> vẫn tô sáng mục "Lịch sử". Không dùng khớp
        // chính xác, nếu không mở trang chi tiết là mất dấu vị trí hiện tại.
        const dangO = pathname === link.href || pathname.startsWith(`${link.href}/`);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={dangO ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-all duration-150 ${
              dangO
                ? "bg-white text-slate-900 shadow-thap ring-1 ring-slate-900/[0.06]"
                : "text-slate-500 hover:text-slate-900"
            }`}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
