import { NextResponse } from "next/server";

import { ApiError } from "@/lib/errors";

/**
 * Bọc mọi Route Handler: dịch lỗi đã phân loại thành JSON cùng hình dạng với
 * ErrorResponse của gateway, và nuốt mọi lỗi khác thành 502 không kèm chi tiết.
 *
 * Vì sao 502 chứ không 500: lỗi lọt tới đây là lỗi khi GỌI gateway (DNS, từ
 * chối kết nối). Nói "lỗi phía trên" đúng hơn "lỗi dashboard", và đó là gợi ý
 * đầu tiên cho người vận hành.
 */
export async function respond<T>(fn: () => Promise<T>, successStatus = 200): Promise<NextResponse> {
  try {
    const data = await fn();
    return NextResponse.json(data ?? { ok: true }, { status: successStatus });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(
        { code: error.code, message: error.message, trace_id: error.traceId },
        { status: error.status },
      );
    }
    // Không đưa error.message ra ngoài: nó chứa host/cổng nội bộ và stack.
    return NextResponse.json(
      { code: "internal", message: "không gọi được gateway", trace_id: null },
      { status: 502 },
    );
  }
}
