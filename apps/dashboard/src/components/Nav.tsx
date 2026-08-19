import Link from "next/link";

const LINKS = [
  { href: "/hosts", label: "Model Hosts" },
  { href: "/services", label: "Services" },
  { href: "/playground", label: "Playground" },
  { href: "/runs", label: "Lịch sử" },
];

export function Nav() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <nav className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        <span className="font-semibold">vypq services</span>
        {LINKS.map((link) => (
          <Link key={link.href} href={link.href} className="text-sm text-slate-600 hover:text-slate-900">
            {link.label}
          </Link>
        ))}
        <form action="/api/logout" method="post" className="ml-auto">
          <button type="submit" className="text-sm text-slate-500 hover:text-slate-900">Đăng xuất</button>
        </form>
      </nav>
    </header>
  );
}
