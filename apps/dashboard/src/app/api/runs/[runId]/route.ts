import type { NextResponse } from "next/server";

import { gateway } from "@/lib/gateway";
import { respond } from "@/lib/route-helpers";

export function GET(
  _request: Request,
  context: { params: Promise<{ runId: string }> },
): Promise<NextResponse> {
  return respond(async () => gateway.getRun((await context.params).runId));
}
