import type { NextResponse } from "next/server";

import { gateway } from "@/lib/gateway";
import { respond } from "@/lib/route-helpers";

export function DELETE(
  _request: Request,
  context: { params: Promise<{ name: string }> },
): Promise<NextResponse> {
  return respond(async () => {
    const { name } = await context.params;
    await gateway.deleteHost(name);
    return { ok: true };
  });
}
