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

/** Chỉ http(s). Chặn ở đây để thông báo chỉ đúng chỗ hỏng — dashboard là cửa
 *  công khai, không phải nơi để một scheme lạ đi tiếp rồi vọng lỗi khó hiểu về. */
function laHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
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
    const coTep = file instanceof File && file.size > 0;
    const inputUri = String(form.get("input_uri") ?? "").trim();
    const modelVersion = String(form.get("model_version") ?? "").trim();

    // Hai nguồn input trong một request là mơ hồ: chọn bừa một cái nghĩa là
    // người dùng nhìn kết quả của thứ mình KHÔNG chọn mà không hề biết.
    if (coTep && inputUri) {
      throw new ApiError(422, "bad_input", "chỉ chọn một: tải tệp lên HOẶC dán URL");
    }
    if (!coTep && !inputUri) {
      throw new ApiError(422, "bad_input", "thiếu file hoặc URL để chạy thử");
    }

    if (inputUri) {
      if (!laHttpUrl(inputUri)) {
        throw new ApiError(422, "bad_input", "URL phải bắt đầu bằng http:// hoặc https://");
      }
      // Không có maxUploadBytes ở nhánh này: dashboard không tải nội dung, nên
      // không có gì để đo. Chốt kích thước là VYPQ_MAX_DOWNLOAD_MB của gateway,
      // nơi thật sự cầm bytes — xem gateway/proxy.py::fetch.
      return gateway.invokeUri(service, inputUri, modelVersion || null);
    }

    const tep = file as File;
    if (tep.size > maxUploadBytes) throw tooLarge(tep.size, maxUploadBytes);
    return gateway.invokeUpload(service, tep, modelVersion || null);
  });
}
