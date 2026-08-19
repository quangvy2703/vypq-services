import "server-only";

export interface ServerEnv {
  gatewayUrl: string;
  gatewayToken: string;
  dashboardPassword: string;
  sessionSecret: string;
  maxUploadBytes: number;
}

/** Khớp `max_inline_mb: 25` trong config của service — gửi to hơn cũng bị chặn ở dưới. */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    // Cùng lập trường với GatewaySettings._token_must_not_be_empty: một dashboard
    // chạy với mật khẩu rỗng là một proxy công khai vào token của mọi máy GPU.
    throw new Error(`${name} bắt buộc phải có — dashboard từ chối khởi động`);
  }
  return value;
}

/**
 * Đọc env tại thời điểm gọi, không phải lúc import module: import xảy ra khi
 * bundle nạp, sớm hơn lúc runtime container có đủ biến, và làm test không stub
 * được.
 */
/** DASHBOARD_AUTH=off: bỏ cổng mật khẩu. Xem AccessInput.authDisabled. */
export function authDisabled(): boolean {
  return process.env.DASHBOARD_AUTH?.trim().toLowerCase() === "off";
}

export function getServerEnv(): ServerEnv {
  // GATEWAY_TOKEN vẫn bắt buộc kể cả khi tắt xác thực: không có nó thì dashboard
  // chẳng gọi được gì. Chỉ hai bí mật của riêng cổng đăng nhập là bỏ được.
  const boQuaDangNhap = authDisabled();
  return {
    gatewayUrl: (process.env.GATEWAY_URL?.trim() || "http://localhost:8080").replace(/\/+$/, ""),
    gatewayToken: required("GATEWAY_TOKEN"),
    dashboardPassword: boQuaDangNhap ? "" : required("DASHBOARD_PASSWORD"),
    sessionSecret: boQuaDangNhap ? "" : required("SESSION_SECRET"),
    maxUploadBytes: MAX_UPLOAD_BYTES,
  };
}
