"use client";

import { useState } from "react";

export function LoginForm() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setPending(true);
    setError(null);
    const body = new FormData();
    body.set("password", password);
    const response = await fetch("/api/login", { method: "POST", body });
    setPending(false);
    if (!response.ok) {
      setError("Sai mật khẩu");
      return;
    }
    // Điều hướng cứng chứ không router.replace: đăng nhập là một lần đổi quyền,
    // và mọi thứ Router Cache phía client ghi lại lúc CHƯA có phiên (mọi trang
    // đều bị middleware đẩy về /login) đều đã sai kể từ giây này. Tải lại cả
    // trang là cách duy nhất chắc chắn vứt hết đống đó đi.
    //
    // Nhóm route (dashboard) — không render Nav trên /login — tự nó cũng đủ sửa
    // lỗi "đăng nhập không đi đâu cả", đã kiểm bằng cách hoàn nguyên riêng từng
    // lớp. Giữ cả hai là cố ý: lớp kia chỉ chặn ĐÚNG MỘT nguồn làm hỏng cache
    // (prefetch của Nav), còn dòng này chặn mọi nguồn khác, kể cả những cái sẽ
    // sinh ra khi ai đó thêm một Link mới ở đâu đó trong tương lai.
    window.location.assign("/hosts");
  }

  return (
    <form
      onSubmit={submit}
      className="w-full max-w-sm space-y-5 rounded-2xl bg-white p-7 shadow-lg ring-1 ring-slate-900/5"
    >
      <div className="space-y-1">
        <span
          aria-hidden
          className="mb-3 grid size-9 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white"
        >
          V
        </span>
        <h1 className="text-lg font-semibold tracking-tight text-slate-900">vypq services</h1>
        <p className="text-sm text-slate-500">Bảng điều khiển các model service.</p>
      </div>

      <label className="block space-y-1.5">
        <span className="block text-xs font-medium text-slate-600">Mật khẩu</span>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-xs transition-colors hover:border-slate-300 focus:border-brand-500"
        />
      </label>

      {error ? (
        <p
          role="alert"
          className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-600/15 ring-inset"
        >
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={pending || password.length === 0}
        className="w-full rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-45"
      >
        {pending ? "Đang kiểm tra…" : "Đăng nhập"}
      </button>
    </form>
  );
}
