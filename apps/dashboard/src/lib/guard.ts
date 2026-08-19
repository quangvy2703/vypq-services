import { verifySession } from "@/lib/session";

export type GuardDecision =
  | { kind: "allow" }
  | { kind: "misconfigured" }
  | { kind: "unauthorized-api" }
  | { kind: "redirect-login" };

/**
 * So khớp chính xác, không dùng startsWith: "/loginhacker" không phải "/login".
 *
 * /api/logout công khai vì đăng xuất phải luôn thành công: phiên hết hạn rồi mà
 * bấm Đăng xuất sẽ nhận 401 JSON thô ngay giữa trang. Route đó chỉ xoá cookie,
 * không đọc dữ liệu gì nên mở ra không lộ thứ gì.
 */
const PUBLIC_PATHS = new Set(["/login", "/api/login", "/api/logout"]);

export interface AccessInput {
  pathname: string;
  sessionToken: string | undefined;
  sessionSecret: string | undefined;
  nowMs: number;
}

export async function decideAccess(input: AccessInput): Promise<GuardDecision> {
  // Kiểm cấu hình TRƯỚC danh sách công khai: thiếu secret thì cả trang đăng nhập
  // cũng vô nghĩa (ký xong không ai kiểm được), nên nói thẳng lỗi cấu hình.
  if (!input.sessionSecret) return { kind: "misconfigured" };
  if (PUBLIC_PATHS.has(input.pathname)) return { kind: "allow" };
  if (await verifySession(input.sessionSecret, input.sessionToken, input.nowMs)) {
    return { kind: "allow" };
  }
  // fetch() từ client component không theo redirect sang HTML được — nó cần một
  // mã lỗi để hiện thông báo, nếu không sẽ parse trang đăng nhập như JSON.
  if (input.pathname.startsWith("/api/")) return { kind: "unauthorized-api" };
  return { kind: "redirect-login" };
}
