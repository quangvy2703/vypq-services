import { NavLinks } from "@/components/NavLinks";
import { authDisabled } from "@/lib/env";

export function Nav() {
  // Tắt xác thực thì không có phiên nào để thoát — hiện nút Đăng xuất lúc đó
  // chỉ dẫn người dùng vào một hành động không làm gì cả.
  const boQuaDangNhap = authDisabled();

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/75 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-6 px-4 sm:px-6">
        <span className="flex shrink-0 items-center gap-2.5 text-[0.9375rem] font-semibold tracking-[-0.01em] text-slate-900">
          <span
            aria-hidden
            className="grid size-7 place-items-center rounded-[0.6rem] bg-linear-to-b from-brand-500 to-brand-700 text-[0.7rem] font-bold text-white shadow-nut"
          >
            V
          </span>
          vypq
          <span className="hidden text-slate-300 sm:inline">/</span>
          <span className="hidden font-normal text-slate-400 sm:inline">services</span>
        </span>

        <div className="hidden md:block">
          <NavLinks />
        </div>

        <div className="ml-auto flex items-center gap-3">
          {boQuaDangNhap ? (
            <span
              title="DASHBOARD_AUTH=off — bất kỳ ai với tới cổng này đều vào được"
              className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 ring-1 ring-amber-600/20 ring-inset"
            >
              <span aria-hidden className="size-1.5 rounded-full bg-amber-500" />
              không xác thực
            </span>
          ) : (
            <form action="/api/logout" method="post">
              <button
                type="submit"
                className="rounded-lg px-2.5 py-1.5 text-sm font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900"
              >
                Đăng xuất
              </button>
            </form>
          )}
        </div>
      </div>

      {/* Thanh nav trên máy hẹp: xuống một hàng riêng thay vì bị nuốt mất. */}
      <div className="cuon-manh -mt-1 overflow-x-auto px-4 pb-2.5 md:hidden">
        <NavLinks />
      </div>
    </header>
  );
}
