import { beforeAll, describe, expect, it } from "vitest";

import { decideAccess } from "@/lib/guard";
import { signSession } from "@/lib/session";

const SECRET = "bi-mat-phien";
const NOW = 1_760_000_000_000;
let valid: string;

beforeAll(async () => {
  valid = await signSession(SECRET, NOW + 60_000);
});

describe("decideAccess", () => {
  it.each(["/login", "/api/login", "/api/logout"])("cho %s đi qua khi chưa đăng nhập", async (pathname) => {
    const decision = await decideAccess({
      pathname, sessionToken: undefined, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("allow");
  });

  it("cho trang đã đăng nhập đi qua", async () => {
    const decision = await decideAccess({
      pathname: "/hosts", sessionToken: valid, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("allow");
  });

  it("đẩy trang chưa đăng nhập về /login", async () => {
    const decision = await decideAccess({
      pathname: "/hosts", sessionToken: undefined, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("redirect-login");
  });

  it("cho đăng xuất đi qua kể cả khi phiên đã hết hạn", async () => {
    // Bấm Đăng xuất với phiên hết hạn mà nhận 401 JSON thô giữa trang là ngõ cụt:
    // người dùng không xoá được cookie hỏng bằng chính nút để làm việc đó.
    const expired = await signSession(SECRET, NOW - 1);
    const decision = await decideAccess({
      pathname: "/api/logout", sessionToken: expired, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("allow");
  });

  it("trả 401 cho API chứ không redirect — fetch() không đọc được trang HTML đăng nhập", async () => {
    const decision = await decideAccess({
      pathname: "/api/hosts", sessionToken: undefined, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("unauthorized-api");
  });

  it("chặn khi thiếu SESSION_SECRET thay vì cho qua", async () => {
    // Không có secret thì không kiểm được chữ ký nào cả. Mở cửa ở đây là biến
    // một lỗi cấu hình thành một dashboard không mật khẩu.
    const decision = await decideAccess({
      pathname: "/hosts", sessionToken: valid, sessionSecret: undefined, nowMs: NOW,
    });
    expect(decision.kind).toBe("misconfigured");
  });

  it("vẫn chặn /login khi thiếu secret — đăng nhập cũng không ký nổi cookie", async () => {
    const decision = await decideAccess({
      pathname: "/login", sessionToken: undefined, sessionSecret: undefined, nowMs: NOW,
    });
    expect(decision.kind).toBe("misconfigured");
  });

  it("đẩy về /login khi phiên hết hạn", async () => {
    const expired = await signSession(SECRET, NOW - 1);
    const decision = await decideAccess({
      pathname: "/hosts", sessionToken: expired, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("redirect-login");
  });

  it("không nhầm /loginhacker là đường công khai", async () => {
    const decision = await decideAccess({
      pathname: "/loginhacker", sessionToken: undefined, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("redirect-login");
  });
});
