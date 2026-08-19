import { NextResponse } from "next/server";

import { getServerEnv } from "@/lib/env";
import { SESSION_COOKIE, SESSION_TTL_MS, constantTimeEqual, signSession } from "@/lib/session";

export async function POST(request: Request): Promise<NextResponse> {
  const form = await request.formData();
  const password = String(form.get("password") ?? "");
  const env = getServerEnv();
  if (!constantTimeEqual(password, env.dashboardPassword)) {
    return NextResponse.json(
      { code: "unauthorized", message: "sai mật khẩu", trace_id: null },
      { status: 401 },
    );
  }
  const expiresAt = Date.now() + SESSION_TTL_MS;
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, await signSession(env.sessionSecret, expiresAt), {
    // httpOnly: JS trong trang không cần đọc cookie này, và không đọc được thì
    // XSS cũng không lấy đi được phiên.
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    expires: new Date(expiresAt),
  });
  return response;
}
