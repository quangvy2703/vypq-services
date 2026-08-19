import type { NextResponse } from "next/server";

import { gateway } from "@/lib/gateway";
import { respond } from "@/lib/route-helpers";

export function GET(): Promise<NextResponse> {
  return respond(() => gateway.listServices());
}
