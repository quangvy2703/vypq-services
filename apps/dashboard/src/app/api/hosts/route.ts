import type { NextResponse } from "next/server";

import { ApiError } from "@/lib/errors";
import { gateway } from "@/lib/gateway";
import { respond } from "@/lib/route-helpers";
import type { HostRegistration } from "@/lib/types";

export function GET(): Promise<NextResponse> {
  return respond(() => gateway.listHosts());
}

function parseRegistration(raw: unknown): HostRegistration {
  const body = (raw ?? {}) as Record<string, unknown>;
  const name = typeof body.name === "string" ? body.name.trim() : "";
  const url = typeof body.url === "string" ? body.url.trim() : "";
  const token = typeof body.token === "string" ? body.token.trim() : "";
  if (!name) throw new ApiError(422, "bad_input", "thiếu tên host");
  if (!url) throw new ApiError(422, "bad_input", "thiếu URL host");
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new ApiError(422, "bad_input", `URL không hợp lệ: ${url}`);
  }
  // Poller của gateway gọi bằng httpx; mọi scheme khác chỉ dẫn tới một host
  // vĩnh viễn đỏ mà không ai hiểu tại sao.
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new ApiError(422, "bad_input", `URL phải là http hoặc https, không phải ${parsed.protocol}`);
  }
  return { name, url, token: token || null };
}

export function POST(request: Request): Promise<NextResponse> {
  return respond(async () => {
    let raw: unknown;
    try {
      raw = await request.json();
    } catch {
      throw new ApiError(422, "bad_input", "thân request không phải JSON hợp lệ");
    }
    return gateway.registerHost(parseRegistration(raw));
  }, 201);
}
