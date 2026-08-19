/** Lỗi đã được phân loại, mang sẵn mã HTTP để Route Handler trả thẳng ra. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly traceId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Lỗi do gateway trả về, phân biệt với lỗi tự dashboard sinh ra. */
export class GatewayError extends ApiError {
  constructor(status: number, code: string, message: string, traceId: string | null = null) {
    super(status, code, message, traceId);
    this.name = "GatewayError";
  }
}
