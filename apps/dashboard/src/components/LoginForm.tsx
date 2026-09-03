"use client";

import { useState } from "react";

import { Button, TextField } from "@/components/ui";

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
      className="w-full max-w-sm space-y-5 rounded-2xl bg-white p-7 shadow-noi ring-1 ring-slate-900/[0.06]"
    >
      <div className="space-y-1">
        {/* Cùng dấu hiệu với thanh nav sau khi đăng nhập: vào rồi thì nhận ra
            ngay mình vẫn ở đúng chỗ vừa gõ mật khẩu. */}
        <span
          aria-hidden
          className="mb-3 grid size-9 place-items-center rounded-[0.7rem] bg-linear-to-b from-brand-500 to-brand-700 text-sm font-bold text-white shadow-nut"
        >
          V
        </span>
        <h1 className="text-lg font-semibold tracking-[-0.01em] text-slate-900">vypq services</h1>
        <p className="text-sm text-slate-500">Bảng điều khiển các model service.</p>
      </div>

      {/* Không truyền `hint`: TextField đặt gợi ý BÊN TRONG <label>, nên nó sẽ
          chui vào tên khả truy cập của ô — mà tên đó phải đúng bằng "Mật khẩu". */}
      <TextField
        label="Mật khẩu"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />

      {error ? (
        <p
          role="alert"
          className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-600/15 ring-inset"
        >
          {error}
        </p>
      ) : null}

      <Button type="submit" size="lg" className="w-full" disabled={pending || password.length === 0}>
        {pending ? "Đang kiểm tra…" : "Đăng nhập"}
      </Button>
    </form>
  );
}
