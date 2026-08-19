import { NextResponse, type NextRequest } from "next/server";

import { decideAccess } from "@/lib/guard";
import { SESSION_COOKIE } from "@/lib/session";

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const decision = await decideAccess({
    pathname: request.nextUrl.pathname,
    sessionToken: request.cookies.get(SESSION_COOKIE)?.value,
    sessionSecret: process.env.SESSION_SECRET?.trim() || undefined,
    nowMs: Date.now(),
    // So khớp CHÍNH XÁC chuỗi "off": mọi giá trị khác — kể cả "false", "0",
    // hay một lỗi gõ — đều giữ nguyên xác thực. Nghiêng về phía khoá.
    authDisabled: process.env.DASHBOARD_AUTH?.trim().toLowerCase() === "off",
  });

  switch (decision.kind) {
    case "allow":
      return NextResponse.next();
    case "misconfigured":
      return NextResponse.json(
        { code: "internal", message: "SESSION_SECRET chưa được cấu hình", trace_id: null },
        { status: 500 },
      );
    case "unauthorized-api":
      return NextResponse.json(
        { code: "unauthorized", message: "phiên đã hết hạn, đăng nhập lại", trace_id: null },
        { status: 401 },
      );
    case "redirect-login": {
      const url = request.nextUrl.clone();
      url.pathname = "/login";
      url.search = "";
      return NextResponse.redirect(url);
    }
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
