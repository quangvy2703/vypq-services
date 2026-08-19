import { NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

export async function POST(request: Request): Promise<NextResponse> {
  // Nav dùng <form method="post"> chứ không fetch, nên đây là một lần điều
  // hướng thật của trình duyệt: trả JSON sẽ ném người dùng vào một trang
  // {"ok":true} trắng trơn, phiên xoá rồi nhưng không có đường quay lại.
  //
  // 303 chứ không 302: buộc trình duyệt đổi POST thành GET khi đi tiếp, nếu
  // không nó sẽ POST lại vào /login.
  const response = NextResponse.redirect(new URL("/login", request.url), 303);
  response.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0 });
  return response;
}
