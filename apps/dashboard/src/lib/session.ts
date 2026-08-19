export const SESSION_COOKIE = "vypq_session";

/** 12 giờ: đủ một ca làm việc, ngắn hơn thời gian thuê một máy GPU điển hình. */
export const SESSION_TTL_MS = 12 * 60 * 60 * 1000;

const encoder = new TextEncoder();

function base64url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function hmac(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return base64url(new Uint8Array(signature));
}

/**
 * So sánh không thoát sớm. Cùng lý do như `secrets.compare_digest` trong
 * gateway/auth.py: `===` dừng ở byte đầu khác nhau và làm rò rỉ độ dài tiền tố
 * đúng qua thời gian phản hồi.
 */
export function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function signSession(secret: string, expiresAtMs: number): Promise<string> {
  const payload = String(expiresAtMs);
  return `${payload}.${await hmac(secret, payload)}`;
}

export async function verifySession(
  secret: string,
  token: string | undefined,
  nowMs: number,
): Promise<boolean> {
  if (!token) return false;
  const separator = token.lastIndexOf(".");
  if (separator <= 0 || separator === token.length - 1) return false;
  const payload = token.slice(0, separator);
  const signature = token.slice(separator + 1);
  // Kiểm chữ ký TRƯỚC khi tin payload: đọc hạn ra rồi mới kiểm là mời người ta
  // tự ghi hạn cho mình.
  if (!constantTimeEqual(signature, await hmac(secret, payload))) return false;
  const expiresAt = Number(payload);
  return Number.isFinite(expiresAt) && nowMs < expiresAt;
}
