import type { NextResponse } from "next/server";

import { getServerEnv } from "@/lib/env";
import { ApiError } from "@/lib/errors";
import { gateway } from "@/lib/gateway";
import { respond } from "@/lib/route-helpers";

function tooLarge(bytes: number, limit: number): ApiError {
  const limitMb = Math.round(limit / (1024 * 1024));
  return new ApiError(
    413,
    "bad_input",
    `file ${(bytes / (1024 * 1024)).toFixed(1)} MB vượt giới hạn ${limitMb} MB`,
  );
}

export function POST(request: Request): Promise<NextResponse> {
  return respond(async () => {
    // Chặn theo Content-Length TRƯỚC khi parse. request.formData() của Next ném
    // lỗi trên body quá lớn, và lỗi đó rơi vào nhánh 502 chung "không gọi được
    // gateway" — người dùng upload nhầm file 200 MB nhận một thông báo nói sai
    // hoàn toàn chỗ hỏng. Content-Length gồm cả phần bao multipart nên nhỉnh
    // hơn kích thước file thật một chút; đó là lý do vẫn giữ phép kiểm
    // file.size bên dưới, nơi biết con số chính xác.
    const { maxUploadBytes } = getServerEnv();
    const declared = Number(request.headers.get("content-length"));
    if (Number.isFinite(declared) && declared > maxUploadBytes) {
      throw tooLarge(declared, maxUploadBytes);
    }

    const form = await request.formData();
    const service = String(form.get("service") ?? "").trim();
    if (!service) throw new ApiError(422, "bad_input", "thiếu service");

    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) {
      throw new ApiError(422, "bad_input", "thiếu file để chạy thử");
    }

    if (file.size > maxUploadBytes) throw tooLarge(file.size, maxUploadBytes);

    const modelVersion = String(form.get("model_version") ?? "").trim();
    return gateway.invokeUpload(service, file, modelVersion || null);
  });
}
