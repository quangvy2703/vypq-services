import type { NextResponse } from "next/server";

import { getServerEnv } from "@/lib/env";
import { ApiError } from "@/lib/errors";
import { gateway } from "@/lib/gateway";
import { respond } from "@/lib/route-helpers";

export function POST(request: Request): Promise<NextResponse> {
  return respond(async () => {
    const form = await request.formData();
    const service = String(form.get("service") ?? "").trim();
    if (!service) throw new ApiError(422, "bad_input", "thiếu service");

    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) {
      throw new ApiError(422, "bad_input", "thiếu file để chạy thử");
    }

    const { maxUploadBytes } = getServerEnv();
    if (file.size > maxUploadBytes) {
      const limitMb = Math.round(maxUploadBytes / (1024 * 1024));
      throw new ApiError(
        413,
        "bad_input",
        `file ${(file.size / (1024 * 1024)).toFixed(1)} MB vượt giới hạn ${limitMb} MB`,
      );
    }

    const modelVersion = String(form.get("model_version") ?? "").trim();
    return gateway.invokeUpload(service, file, modelVersion || null);
  });
}
