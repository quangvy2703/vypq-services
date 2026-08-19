import { describe, expect, it } from "vitest";

import { constantTimeEqual, signSession, verifySession } from "@/lib/session";

const SECRET = "bi-mat-phien";
const NOW = 1_760_000_000_000;
const EXPIRES = NOW + 60_000;

describe("signSession / verifySession", () => {
  it("nhận lại đúng cookie mình vừa ký", async () => {
    const token = await signSession(SECRET, EXPIRES);
    await expect(verifySession(SECRET, token, NOW)).resolves.toBe(true);
  });

  it("từ chối khi hạn đã qua", async () => {
    const token = await signSession(SECRET, EXPIRES);
    await expect(verifySession(SECRET, token, EXPIRES + 1)).resolves.toBe(false);
  });

  it("từ chối khi payload bị sửa để kéo dài hạn", async () => {
    // Đây là lý do tồn tại của chữ ký: payload nằm rõ ràng trong cookie.
    const token = await signSession(SECRET, EXPIRES);
    const signature = token.slice(token.lastIndexOf(".") + 1);
    await expect(verifySession(SECRET, `${EXPIRES + 999_999}.${signature}`, NOW)).resolves.toBe(false);
  });

  it("từ chối chữ ký ký bằng secret khác", async () => {
    const token = await signSession("secret-khac", EXPIRES);
    await expect(verifySession(SECRET, token, NOW)).resolves.toBe(false);
  });

  it("từ chối khi không có cookie", async () => {
    await expect(verifySession(SECRET, undefined, NOW)).resolves.toBe(false);
  });

  it.each(["", ".", "khongcodauchamnao", `${EXPIRES}.`, `.chuky`])(
    "từ chối cookie sai định dạng %j",
    async (token) => {
      await expect(verifySession(SECRET, token, NOW)).resolves.toBe(false);
    },
  );

  it("từ chối payload không phải số", async () => {
    const token = await signSession(SECRET, EXPIRES);
    const signature = token.slice(token.lastIndexOf(".") + 1);
    await expect(verifySession(SECRET, `mai-mai.${signature}`, NOW)).resolves.toBe(false);
  });
});

describe("constantTimeEqual", () => {
  it("đúng khi hai chuỗi giống hệt", () => {
    expect(constantTimeEqual("abcdef", "abcdef")).toBe(true);
  });

  it("sai khi khác nội dung", () => {
    expect(constantTimeEqual("abcdef", "abcdeg")).toBe(false);
  });

  it("sai khi khác độ dài, không ném", () => {
    expect(constantTimeEqual("abc", "abcdef")).toBe(false);
  });

  it("sai khi một bên rỗng — mật khẩu rỗng không được coi là khớp", () => {
    expect(constantTimeEqual("", "matkhau")).toBe(false);
  });
});
