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
    <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-lg font-semibold">vypq services</h1>
      <label className="block space-y-1">
        <span className="text-sm text-slate-600">Mật khẩu</span>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="w-full rounded border border-slate-300 px-3 py-2"
        />
      </label>
      {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : null}
      <button
        type="submit"
        disabled={pending || password.length === 0}
        className="w-full rounded bg-slate-900 px-3 py-2 text-white disabled:opacity-40"
      >
        {pending ? "Đang kiểm tra…" : "Đăng nhập"}
      </button>
    </form>
  );
}
