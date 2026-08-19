import { NavLinks } from "@/components/NavLinks";
import { authDisabled } from "@/lib/env";

export function Nav() {
  // Tắt xác thực thì không có phiên nào để thoát — hiện nút Đăng xuất lúc đó
  // chỉ dẫn người dùng vào một hành động không làm gì cả.
  const boQuaDangNhap = authDisabled();

  return (
    <header className="sticky top-0 z-10 border-b border-slate-200/80 bg-white/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
        <span className="flex items-center gap-2 font-semibold tracking-tight text-slate-900">
          <span
            aria-hidden
            className="grid size-6 place-items-center rounded-md bg-brand-600 text-[0.65rem] font-bold text-white"
          >
            V
          </span>
          vypq
        </span>

        <NavLinks />

        <div className="ml-auto flex items-center gap-3">
          {boQuaDangNhap ? (
            <span
              title="DASHBOARD_AUTH=off — bất kỳ ai với tới cổng này đều vào được"
              className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-amber-600/20 ring-inset"
            >
              không xác thực
            </span>
          ) : (
            <form action="/api/logout" method="post">
              <button
                type="submit"
                className="rounded-lg px-2.5 py-1.5 text-sm text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900"
              >
                Đăng xuất
              </button>
            </form>
          )}
        </div>
      </div>
    </header>
  );
}
