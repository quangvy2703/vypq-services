"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function LoginForm() {
  const router = useRouter();
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
    // replace chứ không push: nút Back không nên quay về trang đăng nhập.
    router.replace("/hosts");
    router.refresh();
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
