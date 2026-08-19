# Plan B2 — Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng `apps/dashboard` — trang quản lí trung tâm để cắm máy GPU thuê vào, xem service, test thử OCR/ASR có overlay bbox, so sánh nhiều model trên cùng một input, và tra lịch sử chạy.

**Architecture:** Next.js App Router chạy như một **BFF (backend-for-frontend)**: trình duyệt chỉ nói chuyện với server Next (cùng origin), server Next mới cầm `GATEWAY_TOKEN` gọi sang gateway của Plan B1. Token gateway **không bao giờ** rời khỏi tiến trình Node — không nằm trong biến `NEXT_PUBLIC_*`, không nằm trong client component, không nằm trong payload RSC. Đọc dữ liệu đi qua Server Component gọi thẳng `src/lib/gateway.ts`; ghi và tương tác đi qua Route Handler dưới `src/app/api/*`. Bản thân dashboard có một cổng mật khẩu riêng (cookie ký HMAC) vì nếu không, ai với tới cổng 3001 sẽ có nguyên quyền của một token gateway hợp lệ.

**Tech Stack:** Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind CSS v4 · Vitest + Testing Library (unit/component) · Playwright (e2e, chạy với gateway giả tự dựng) · pnpm

---

## Bối cảnh — đọc trước khi làm bất cứ task nào

Gateway (Plan B1, đã merge) là **nguồn dữ liệu duy nhất** của dashboard. Mọi route `/v1/*` đều đòi `Authorization: Bearer <VYPQ_TOKEN>`; không có route nào miễn token.

| Method | Path | Trả về |
|---|---|---|
| `GET` | `/v1/hosts` | `HostsResponse` — **không** mang `token` của host |
| `POST` | `/v1/hosts` | `HostState` (201) |
| `DELETE` | `/v1/hosts/{name}` | 204, hoặc 404 nếu không có tên đó |
| `GET` | `/v1/discovery/hosts` | **MANG TOKEN CỦA MÁY GPU — dashboard TUYỆT ĐỐI KHÔNG ĐƯỢC GỌI** |
| `GET` | `/v1/services` | `ServicesResponse` |
| `POST` | `/v1/invoke/upload` | multipart (`service`, `model_version?`, `file`) → `InvokeResponse` |
| `POST` | `/v1/invoke` | JSON (`service`, `input_uri`, `mode`, `model_version?`) → `InvokeResponse` |
| `GET` | `/v1/runs` | `RunsResponse`; query `trace_id`, `service`, `status`, `limit` (1..200), `offset` (≥0) |
| `GET` | `/v1/runs/{run_id}` | `RunRecord`, hoặc 404 |

**Ba sự thật về dữ liệu mà UI phải tôn trọng — sai chỗ này là sai chức năng, không phải sai thẩm mỹ:**

1. **`ServiceState.info` có thể là `null`.** Nghĩa là gateway CHƯA TỪNG poll thành công service đó, nên chưa biết `task`, `capability_*`, `invoke_path`. Dashboard **không được đoán** — phải hiện "chưa liên hệ được" và không cho chọn service đó trong playground.
2. **Đường sync ghi `input_uri = null`** (xem `SyncProxy.invoke`). Nên trang chi tiết run **không có ảnh gốc** để vẽ overlay lên. `OcrViewer` bắt buộc phải vẽ được bbox trên nền trắng khi không có ảnh; chỉ playground (đang cầm file trong trình duyệt) mới có ảnh thật.
3. **`RunRecord.output` là `result` của service**, không phải cả body: OCR → `{full_text, boxes}`, ASR → `{text, segments}`. `output` có thể là `null` (run `failed` hoặc `pending`).

Giá trị capability thật đang chạy:

| service | `task` | `capability_input` | `capability_output` | `invoke_path` |
|---|---|---|---|---|
| `ocr` | `ocr` | `image` | `text_boxes` | `/v1/ocr` |
| `asr` | `asr` | `audio` | `transcript` | `/v1/asr` |
| `_template` | (tuỳ) | `bytes` | `json` | (tuỳ) |

Spec §3.8 yêu cầu: **service thứ ba (NER, TTS...) chỉ cần trả đúng `/v1/info` là dùng được, không sửa code dashboard.** Đó là lý do mọi chỗ chọn uploader/viewer phải đi qua `src/lib/capability.ts` và phải có nhánh fallback `json`, chứ không được `if (task === "ocr")` rải khắp nơi.

**Lệch so với spec, cố ý:** spec §5 ghi `Next.js + TS + Tailwind + shadcn`. Plan này **không dùng shadcn/ui**. Lý do: shadcn là một CLI sinh code vào repo và kéo theo Radix; số component thật sự cần ở đây (badge, card, button, field, table, empty-state) là ~6 cái nhỏ, viết tay rẻ hơn và toàn bộ code nằm trong plan này để review được. Tailwind vẫn giữ nguyên như spec.

**Ngoài phạm vi B2, đừng làm:** chấm điểm tự động (CER/WER/IoU), leaderboard, trang `benchmarks`, trang `models` riêng, DLQ viewer, nhúng Grafana. Đó là Plan C và bước 10 của lộ trình. B2 chỉ so sánh **cạnh nhau** kèm thống kê mô tả (số box, số ký tự, số segment, độ trễ) — không có ground truth thì không có điểm.

---

## Global Constraints

- **Token gateway chỉ tồn tại phía server.** Không `NEXT_PUBLIC_GATEWAY_TOKEN`, không truyền token vào props của client component, không log token. Mọi file chạm `src/lib/gateway.ts` hoặc `src/lib/env.ts` phải là server-only.
- **Dashboard từ chối khởi động khi thiếu bí mật.** `GATEWAY_TOKEN`, `DASHBOARD_PASSWORD`, `SESSION_SECRET` thiếu → ném lỗi, không chạy tiếp với chuỗi rỗng. Cùng lập trường với `GatewaySettings._token_must_not_be_empty`.
- **Không gọi `/v1/discovery/hosts`** từ bất kỳ đâu trong dashboard.
- **Cổng 3001.** Cổng 3000 đã là Grafana trong `infra/compose/docker-compose.dev.yml`.
- **Giới hạn upload 25 MB**, khớp `max_inline_mb: 25` của service.
- **TypeScript `strict: true` + `noUncheckedIndexedAccess: true`.** Không `any` trong code commit. `pnpm lint` (= `tsc --noEmit`) phải sạch.
- **Chú thích bằng tiếng Việt**, giống toàn bộ codebase Python hiện có. Chú thích giải thích *tại sao*, không mô tả lại code.
- **Không thêm thư viện UI** (shadcn, Radix, MUI, chart lib). Dependency mới ngoài danh sách ở Task 1 phải hỏi trước.
- **Mọi giá trị capability đọc từ gateway**, không hardcode `"ocr"`/`"asr"` trong page/component; đi qua `src/lib/capability.ts`.
- **`vitest run` phải xanh và không cần mạng, không cần Docker.**

---

## File Structure

```
apps/dashboard/
├── package.json  tsconfig.json  next.config.ts  postcss.config.mjs
├── vitest.config.ts  vitest.setup.ts  playwright.config.ts
├── Dockerfile  .env.example  .dockerignore
├── src/
│   ├── middleware.ts                  # dịch quyết định của lib/guard.ts sang NextResponse
│   ├── lib/
│   │   ├── env.ts                     # đọc env phía server, thiếu bí mật thì ném
│   │   ├── errors.ts                  # ApiError / GatewayError
│   │   ├── types.ts                   # bản TS của vypq_contracts (gateway/ocr/asr)
│   │   ├── gateway.ts                 # client HTTP duy nhất đi ra gateway (server-only)
│   │   ├── session.ts                 # ký/kiểm cookie phiên bằng HMAC WebCrypto
│   │   ├── guard.ts                   # decideAccess() thuần, không phụ thuộc Next
│   │   ├── route-helpers.ts           # respond(): map lỗi → JSON, không lộ stack
│   │   ├── capability.ts              # capability → uploader accept + loại viewer
│   │   ├── results.ts                 # type guard: unknown → OcrResult | AsrResult
│   │   ├── pagination.ts              # buildPageHref() thuần
│   │   └── format.ts                  # formatMs / formatTimestamp / formatClock / relativeTime
│   ├── app/
│   │   ├── layout.tsx  globals.css  page.tsx
│   │   ├── login/page.tsx
│   │   ├── hosts/page.tsx
│   │   ├── services/page.tsx
│   │   ├── playground/page.tsx
│   │   ├── runs/page.tsx
│   │   ├── runs/[runId]/page.tsx
│   │   └── api/
│   │       ├── login/route.ts  logout/route.ts
│   │       ├── hosts/route.ts  hosts/[name]/route.ts
│   │       ├── services/route.ts
│   │       ├── invoke/route.ts
│   │       └── runs/route.ts  runs/[runId]/route.ts
│   └── components/
│       ├── ui.tsx  Nav.tsx  LoginForm.tsx
│       ├── HostsPanel.tsx  ServicesTable.tsx
│       ├── Playground.tsx  RunsTable.tsx
│       └── viewers/OcrViewer.tsx  AsrViewer.tsx  ResultViewer.tsx
└── tests/
    ├── stubs/server-only.ts
    ├── unit/*.test.ts(x)
    └── e2e/fake-gateway.mjs  e2e/main-flow.spec.ts
```

Trách nhiệm từng file được khoá ở đây: `lib/*` thuần và test được không cần Next; `app/api/*` chỉ dịch HTTP ↔ `lib/gateway`; `app/*/page.tsx` là Server Component chỉ lấy dữ liệu rồi giao cho component; `components/*` không biết gì về token, chỉ gọi `/api/*` cùng origin.

---
### Task 1: Dựng khung `apps/dashboard` + bộ test chạy được

**Files:**
- Create: `apps/dashboard/package.json`, `apps/dashboard/tsconfig.json`, `apps/dashboard/next.config.ts`, `apps/dashboard/postcss.config.mjs`, `apps/dashboard/vitest.config.ts`, `apps/dashboard/vitest.setup.ts`, `apps/dashboard/tests/stubs/server-only.ts`
- Create: `apps/dashboard/src/app/layout.tsx`, `apps/dashboard/src/app/globals.css`, `apps/dashboard/src/app/page.tsx`, `apps/dashboard/src/lib/format.ts`
- Test: `apps/dashboard/tests/unit/format.test.ts`
- Modify: `Makefile`

**Interfaces:**
- Consumes: không có (task đầu tiên).
- Produces: `formatMs(ms: number | null): string`, `formatTimestamp(iso: string | null): string`, `formatClock(seconds: number): string`, `relativeTime(iso: string | null, nowMs: number): string` từ `@/lib/format`. Alias `@/*` → `src/*`. Lệnh `pnpm test`, `pnpm lint` chạy được trong `apps/dashboard`.

- [ ] **Step 1: Tạo thư mục và cài dependency**

Chạy từ gốc repo:

```bash
mkdir -p apps/dashboard/src/app apps/dashboard/src/lib apps/dashboard/src/components apps/dashboard/tests/unit apps/dashboard/tests/stubs
cd apps/dashboard
cat > package.json <<'JSON'
{
  "name": "vypq-dashboard",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "next dev -p 3001",
    "build": "next build",
    "start": "next start -p 3001",
    "lint": "tsc --noEmit",
    "test": "vitest run",
    "test:e2e": "playwright test"
  }
}
JSON
pnpm add next@^15 react@^19 react-dom@^19 server-only
pnpm add -D typescript@^5 @types/node@^22 @types/react@^19 @types/react-dom@^19 \
  tailwindcss@^4 @tailwindcss/postcss@^4 \
  vitest@^3 jsdom@^26 @vitejs/plugin-react@^4 \
  @testing-library/react@^16 @testing-library/dom@^10 @testing-library/user-event@^14 @testing-library/jest-dom@^6
```

Expected: `pnpm-lock.yaml` và `node_modules/` xuất hiện trong `apps/dashboard`, không lỗi.

- [ ] **Step 2: Viết file cấu hình**

`apps/dashboard/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "ES2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"],
    "plugins": [{ "name": "next" }],
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

`apps/dashboard/next.config.ts`:

```ts
import type { NextConfig } from "next";

const config: NextConfig = {
  // standalone để Dockerfile ở Task 13 copy đúng một cây runtime nhỏ,
  // không phải bê cả node_modules dev vào image.
  output: "standalone",
  reactStrictMode: true,
};

export default config;
```

`apps/dashboard/postcss.config.mjs`:

```js
export default { plugins: { "@tailwindcss/postcss": {} } };
```

`apps/dashboard/tests/stubs/server-only.ts`:

```ts
// Gói `server-only` cố tình NÉM khi bị import ngoài môi trường react-server —
// đó chính là tác dụng của nó trong bundle. Vitest không có điều kiện đó, nên
// alias sang file rỗng này để test vẫn import được lib/env, lib/gateway.
export {};
```

`apps/dashboard/vitest.config.ts`:

```ts
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "server-only": fileURLToPath(new URL("./tests/stubs/server-only.ts", import.meta.url)),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
  },
});
```

`apps/dashboard/vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
```

- [ ] **Step 3: Viết test thất bại cho `lib/format.ts`**

`apps/dashboard/tests/unit/format.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { formatClock, formatMs, formatTimestamp, relativeTime } from "@/lib/format";

describe("formatMs", () => {
  it("hiện mili giây khi dưới một giây", () => {
    expect(formatMs(842)).toBe("842 ms");
  });

  it("đổi sang giây khi từ một giây trở lên", () => {
    expect(formatMs(1500)).toBe("1.50 s");
  });

  it("trả gạch ngang khi chưa có số liệu", () => {
    // run pending và run failed đều có latency_ms = null; hiện "0 ms" ở đó là nói dối.
    expect(formatMs(null)).toBe("—");
  });
});

describe("formatClock", () => {
  it("định dạng mốc thời gian của segment ASR theo mm:ss.s", () => {
    expect(formatClock(0)).toBe("00:00.0");
    expect(formatClock(75.42)).toBe("01:15.4");
  });

  it("giữ được đoạn dài hơn một giờ", () => {
    expect(formatClock(3725.5)).toBe("62:05.5");
  });
});

describe("formatTimestamp", () => {
  it("giữ nguyên phần ngày và giờ theo UTC", () => {
    expect(formatTimestamp("2026-08-19T07:05:09.123456Z")).toBe("2026-08-19 07:05:09");
  });

  it("trả gạch ngang khi null", () => {
    expect(formatTimestamp(null)).toBe("—");
  });

  it("trả nguyên chuỗi khi không phải ngày hợp lệ", () => {
    // Thà hiện thứ gateway thật sự trả về còn hơn hiện "Invalid Date".
    expect(formatTimestamp("khong-phai-ngay")).toBe("khong-phai-ngay");
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-08-19T07:00:00Z");

  it("đếm giây khi vừa mới đây", () => {
    expect(relativeTime("2026-08-19T06:59:50Z", now)).toBe("10 giây trước");
  });

  it("đếm phút", () => {
    expect(relativeTime("2026-08-19T06:52:00Z", now)).toBe("8 phút trước");
  });

  it("đếm giờ", () => {
    expect(relativeTime("2026-08-19T04:00:00Z", now)).toBe("3 giờ trước");
  });

  it("trả 'chưa từng' khi null", () => {
    // host vừa đăng ký chưa poll lần nào: last_seen_at = null.
    expect(relativeTime(null, now)).toBe("chưa từng");
  });

  it("không hiện thời gian âm khi đồng hồ hai máy lệch nhau", () => {
    expect(relativeTime("2026-08-19T07:00:30Z", now)).toBe("vừa xong");
  });
});
```

- [ ] **Step 4: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test`
Expected: FAIL — `Failed to resolve import "@/lib/format"`.

- [ ] **Step 5: Viết `src/lib/format.ts`**

```ts
const DASH = "—";

export function formatMs(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return DASH;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatClock(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return DASH;
  const parsed = Date.parse(iso);
  // Gateway trả ISO của Postgres; nếu một ngày nào đó nó đổi định dạng, hiện
  // nguyên chuỗi để người vận hành thấy được cái sai, thay vì "Invalid Date".
  if (Number.isNaN(parsed)) return iso;
  return new Date(parsed).toISOString().replace("T", " ").slice(0, 19);
}

export function relativeTime(iso: string | null, nowMs: number): string {
  if (!iso) return "chưa từng";
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return iso;
  const deltaS = Math.floor((nowMs - parsed) / 1000);
  // Máy GPU thuê và máy ứng dụng là hai đồng hồ khác nhau; lệch vài giây là
  // bình thường và "-3 giây trước" trông như lỗi hệ thống.
  if (deltaS < 5) return "vừa xong";
  if (deltaS < 60) return `${deltaS} giây trước`;
  if (deltaS < 3600) return `${Math.floor(deltaS / 60)} phút trước`;
  if (deltaS < 86400) return `${Math.floor(deltaS / 3600)} giờ trước`;
  return `${Math.floor(deltaS / 86400)} ngày trước`;
}
```

- [ ] **Step 6: Chạy test, xác nhận xanh**

Run: `cd apps/dashboard && pnpm test`
Expected: PASS — 14 test.

- [ ] **Step 7: Viết layout tối thiểu để `next build` chạy được**

`apps/dashboard/src/app/globals.css`:

```css
@import "tailwindcss";

:root {
  color-scheme: light;
}

body {
  @apply bg-slate-50 text-slate-900 antialiased;
}
```

`apps/dashboard/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "vypq services",
  description: "Bảng điều khiển các model service",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
```

`apps/dashboard/src/app/page.tsx`:

```tsx
import { redirect } from "next/navigation";

export default function Home() {
  // Trang chủ không có nội dung riêng — thứ người ta mở dashboard để làm đầu
  // tiên là cắm máy GPU vừa thuê vào.
  redirect("/hosts");
}
```

- [ ] **Step 8: Kiểm typecheck và build**

Run: `cd apps/dashboard && pnpm lint && pnpm build`
Expected: `tsc` không báo lỗi; `next build` in `Compiled successfully` và tạo `.next/`.

- [ ] **Step 9: Nối vào Makefile ở gốc repo**

Sửa `Makefile`, dòng đầu thành `.PHONY: test test-all test-web lint lint-web fmt typecheck` và thêm vào cuối file:

```makefile
test-web:
	cd apps/dashboard && pnpm install --frozen-lockfile && pnpm test
lint-web:
	cd apps/dashboard && pnpm install --frozen-lockfile && pnpm lint
```

Run: `make test-web`
Expected: PASS — 14 test.

- [ ] **Step 10: Commit**

`.gitignore` ở gốc đã có `node_modules/` và `.next/`, không cần sửa.

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard Makefile
git commit -m "feat(dashboard): dựng khung Next.js + Vitest cho apps/dashboard"
```

---
### Task 2: Kiểu dữ liệu + client gateway phía server

**Files:**
- Create: `apps/dashboard/src/lib/types.ts`, `apps/dashboard/src/lib/errors.ts`, `apps/dashboard/src/lib/env.ts`, `apps/dashboard/src/lib/gateway.ts`
- Test: `apps/dashboard/tests/unit/env.test.ts`, `apps/dashboard/tests/unit/gateway.test.ts`

**Interfaces:**
- Consumes: alias `@/*` và bộ Vitest từ Task 1.
- Produces:
  - `@/lib/types`: `Task`, `ModelKind`, `HealthStatus`, `InvokeMode`, `RunStatus`, `ModelInfo`, `HostState`, `HostsResponse`, `HostRegistration`, `ServiceInfo`, `ServiceState`, `ServicesResponse`, `InvokeResponse`, `RunRecord`, `RunsResponse`, `RunsQuery`, `TextBox`, `OcrResult`, `Segment`, `AsrResult`.
  - `@/lib/errors`: `class ApiError { status: number; code: string; message: string; traceId: string | null }`, `class GatewayError extends ApiError`.
  - `@/lib/env`: `getServerEnv(): ServerEnv` với `{ gatewayUrl, gatewayToken, dashboardPassword, sessionSecret, maxUploadBytes }`.
  - `@/lib/gateway`: object `gateway` với `listHosts()`, `registerHost(reg)`, `deleteHost(name)`, `listServices()`, `invokeUpload(service, file, modelVersion)`, `listRuns(query)`, `getRun(runId)`.

- [ ] **Step 1: Viết `src/lib/types.ts`**

Đây là bản chép tay của `packages/vypq-contracts` sang TypeScript. Giữ đúng tên field snake_case như JSON gateway trả về — đổi sang camelCase ở đây sẽ tạo một tầng dịch phải bảo trì hai chiều.

```ts
export type Task = "ocr" | "asr";
export type ModelKind = "opensource" | "finetuned";
export type HealthStatus = "ok" | "degraded" | "down";
export type InvokeMode = "sync" | "async";
export type RunStatus = "pending" | "ok" | "failed";

export interface ModelInfo {
  id: string;
  task: Task;
  kind: ModelKind;
  runner: string;
  loaded: boolean;
  available: boolean;
  vram_mb: number;
  base: string | null;
  trained_on: string | null;
}

export interface HostRegistration {
  name: string;
  url: string;
  token: string | null;
}

/** KHÔNG có `token`: /v1/hosts cố tình không trả token của máy GPU. */
export interface HostState {
  name: string;
  url: string;
  healthy: boolean;
  models: ModelInfo[];
  last_seen_at: string | null;
  last_error: string | null;
}

export interface HostsResponse {
  hosts: HostState[];
}

export interface ServiceInfo {
  name: string;
  task: Task;
  capability_input: string;
  capability_output: string;
  version: string;
  invoke_path: string;
  default_model: string | null;
}

export interface ServiceState {
  /** null = gateway chưa từng poll thành công. Không được đoán task. */
  info: ServiceInfo | null;
  base_url: string;
  status: HealthStatus;
  last_seen_at: string | null;
}

export interface ServicesResponse {
  services: ServiceState[];
}

export interface InvokeResponse {
  trace_id: string;
  mode: InvokeMode;
  run_id: string | null;
  result: Record<string, unknown> | null;
}

export interface RunRecord {
  id: string;
  trace_id: string;
  service: string;
  model_version: string | null;
  mode: InvokeMode;
  status: RunStatus;
  input_uri: string | null;
  output: Record<string, unknown> | null;
  latency_ms: number | null;
  error: string | null;
  created_at: string;
}

export interface RunsResponse {
  runs: RunRecord[];
  total: number;
}

export interface RunsQuery {
  trace_id?: string;
  service?: string;
  status?: RunStatus;
  limit?: number;
  offset?: number;
}

export type Polygon = [number, number][];

export interface TextBox {
  id: number;
  polygon: Polygon;
  text: string;
  confidence: number | null;
  ignore: boolean;
}

export interface OcrResult {
  full_text: string;
  boxes: TextBox[];
}

export interface Segment {
  start: number;
  end: number;
  text: string;
  speaker: string | null;
}

export interface AsrResult {
  text: string;
  segments: Segment[];
}
```

- [ ] **Step 2: Viết `src/lib/errors.ts`**

```ts
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
```

- [ ] **Step 3: Viết test thất bại cho `env.ts`**

`apps/dashboard/tests/unit/env.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { getServerEnv } from "@/lib/env";

afterEach(() => {
  vi.unstubAllEnvs();
});

function stubAll(): void {
  vi.stubEnv("GATEWAY_TOKEN", "token-gateway");
  vi.stubEnv("DASHBOARD_PASSWORD", "matkhau");
  vi.stubEnv("SESSION_SECRET", "bi-mat-phien");
}

describe("getServerEnv", () => {
  it("đọc đủ ba bí mật và mặc định gatewayUrl về localhost", () => {
    stubAll();
    vi.stubEnv("GATEWAY_URL", "");
    const env = getServerEnv();
    expect(env.gatewayToken).toBe("token-gateway");
    expect(env.dashboardPassword).toBe("matkhau");
    expect(env.sessionSecret).toBe("bi-mat-phien");
    expect(env.gatewayUrl).toBe("http://localhost:8080");
  });

  it("cắt dấu / thừa ở cuối GATEWAY_URL", () => {
    // Nối "http://gateway:8080/" với "/v1/hosts" ra "//v1/hosts" — gateway trả 404
    // và triệu chứng trông hệt như route không tồn tại.
    stubAll();
    vi.stubEnv("GATEWAY_URL", "http://gateway:8080///");
    expect(getServerEnv().gatewayUrl).toBe("http://gateway:8080");
  });

  it.each(["GATEWAY_TOKEN", "DASHBOARD_PASSWORD", "SESSION_SECRET"])(
    "từ chối chạy khi thiếu %s",
    (name) => {
      stubAll();
      vi.stubEnv(name, "");
      expect(() => getServerEnv()).toThrow(new RegExp(`${name}.*từ chối khởi động`));
    },
  );

  it("coi biến chỉ có khoảng trắng là thiếu", () => {
    stubAll();
    vi.stubEnv("SESSION_SECRET", "   ");
    expect(() => getServerEnv()).toThrow(/SESSION_SECRET/);
  });

  it("giới hạn upload đúng 25 MB, khớp max_inline_mb của service", () => {
    stubAll();
    expect(getServerEnv().maxUploadBytes).toBe(25 * 1024 * 1024);
  });
});
```

- [ ] **Step 4: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/env.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/env"`.

- [ ] **Step 5: Viết `src/lib/env.ts`**

```ts
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
export function getServerEnv(): ServerEnv {
  return {
    gatewayUrl: (process.env.GATEWAY_URL?.trim() || "http://localhost:8080").replace(/\/+$/, ""),
    gatewayToken: required("GATEWAY_TOKEN"),
    dashboardPassword: required("DASHBOARD_PASSWORD"),
    sessionSecret: required("SESSION_SECRET"),
    maxUploadBytes: MAX_UPLOAD_BYTES,
  };
}
```

- [ ] **Step 6: Chạy test, xác nhận xanh**

Run: `cd apps/dashboard && pnpm test tests/unit/env.test.ts`
Expected: PASS — 7 test.

- [ ] **Step 7: Viết test thất bại cho `gateway.ts`**

`apps/dashboard/tests/unit/gateway.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GatewayError } from "@/lib/errors";
import { gateway } from "@/lib/gateway";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubEnv("GATEWAY_URL", "http://gateway:8080");
  vi.stubEnv("GATEWAY_TOKEN", "token-gateway");
  vi.stubEnv("DASHBOARD_PASSWORD", "matkhau");
  vi.stubEnv("SESSION_SECRET", "bi-mat-phien");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function lastCall(): [string, RequestInit] {
  const call = fetchMock.mock.calls.at(-1);
  if (!call) throw new Error("fetch chưa được gọi");
  return [String(call[0]), (call[1] ?? {}) as RequestInit];
}

describe("gateway.listHosts", () => {
  it("gắn bearer token và gọi đúng /v1/hosts", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ hosts: [] }));
    await gateway.listHosts();
    const [url, init] = lastCall();
    expect(url).toBe("http://gateway:8080/v1/hosts");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer token-gateway");
  });

  it("không bao giờ cache — host thuê theo giờ đổi trạng thái liên tục", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ hosts: [] }));
    await gateway.listHosts();
    expect(lastCall()[1].cache).toBe("no-store");
  });
});

describe("gateway.registerHost", () => {
  it("POST kèm thân JSON", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ name: "a100", url: "https://x.ngrok.app" }, 201));
    await gateway.registerHost({ name: "a100", url: "https://x.ngrok.app", token: "bi-mat" });
    const [url, init] = lastCall();
    expect(url).toBe("http://gateway:8080/v1/hosts");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      name: "a100",
      url: "https://x.ngrok.app",
      token: "bi-mat",
    });
  });
});

describe("gateway.deleteHost", () => {
  it("chịu được 204 không có thân", async () => {
    // Response 204 mà gọi .json() sẽ ném "Unexpected end of JSON input";
    // triệu chứng là xoá host thành công nhưng UI báo lỗi.
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(gateway.deleteHost("a100")).resolves.toBeUndefined();
    expect(lastCall()[1].method).toBe("DELETE");
  });

  it("mã hoá tên host trong đường dẫn", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await gateway.deleteHost("máy a/100");
    expect(lastCall()[0]).toBe("http://gateway:8080/v1/hosts/m%C3%A1y%20a%2F100");
  });
});

describe("gateway.listRuns", () => {
  it("chỉ đưa vào query những tham số thật sự có", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ runs: [], total: 0 }));
    await gateway.listRuns({ service: "ocr", limit: 20, offset: 40 });
    expect(lastCall()[0]).toBe("http://gateway:8080/v1/runs?service=ocr&limit=20&offset=40");
  });

  it("không gửi query rỗng khi không lọc gì", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ runs: [], total: 0 }));
    await gateway.listRuns({});
    expect(lastCall()[0]).toBe("http://gateway:8080/v1/runs");
  });
});

describe("gateway.invokeUpload", () => {
  it("gửi multipart với đúng tên field gateway đang chờ", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} }));
    const file = new File([new Uint8Array([1, 2, 3])], "hoadon.png", { type: "image/png" });
    await gateway.invokeUpload("ocr", file, "paddleocr-v4-vi");
    const body = lastCall()[1].body as FormData;
    expect(body.get("service")).toBe("ocr");
    expect(body.get("model_version")).toBe("paddleocr-v4-vi");
    expect((body.get("file") as File).name).toBe("hoadon.png");
  });

  it("bỏ hẳn model_version khi người dùng để trống, để service tự chọn default", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} }));
    const file = new File([new Uint8Array([1])], "a.png", { type: "image/png" });
    await gateway.invokeUpload("ocr", file, null);
    expect((lastCall()[1].body as FormData).has("model_version")).toBe(false);
  });

  it("không tự đặt content-type: boundary của multipart phải do runtime sinh", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ trace_id: "t1", mode: "sync", run_id: null, result: null }));
    const file = new File([new Uint8Array([1])], "a.png", { type: "image/png" });
    await gateway.invokeUpload("ocr", file, null);
    expect(new Headers(lastCall()[1].headers).get("content-type")).toBeNull();
  });
});

describe("ánh xạ lỗi", () => {
  it("giữ nguyên mã HTTP, code và trace_id gateway trả về", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ code: "model_unavailable", message: "service 'ocr' đang không phản hồi", trace_id: "abc" }, 503),
    );
    await expect(gateway.listServices()).rejects.toMatchObject({
      status: 503,
      code: "model_unavailable",
      message: "service 'ocr' đang không phản hồi",
      traceId: "abc",
    });
  });

  it("vẫn ra GatewayError khi thân lỗi không phải JSON", async () => {
    fetchMock.mockResolvedValue(new Response("<html>502 Bad Gateway</html>", { status: 502 }));
    const error = await gateway.listHosts().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(GatewayError);
    expect((error as GatewayError).status).toBe(502);
  });

  it("không để lộ token trong thông điệp lỗi 401", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ code: "bad_input", message: "token không hợp lệ" }, 401));
    const error = await gateway.listHosts().catch((e: unknown) => e);
    expect(JSON.stringify(error, Object.getOwnPropertyNames(error))).not.toContain("token-gateway");
  });
});
```

- [ ] **Step 8: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/gateway.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/gateway"`.

- [ ] **Step 9: Viết `src/lib/gateway.ts`**

```ts
import "server-only";

import { getServerEnv } from "@/lib/env";
import { GatewayError } from "@/lib/errors";
import type {
  HostRegistration,
  HostState,
  HostsResponse,
  InvokeResponse,
  RunRecord,
  RunsQuery,
  RunsResponse,
  ServicesResponse,
} from "@/lib/types";

async function toGatewayError(response: Response): Promise<GatewayError> {
  // Gateway trả ErrorResponse {code, message, trace_id} cho lỗi của nó, nhưng
  // một proxy/ingress đứng giữa có thể trả HTML — vẫn phải ra GatewayError chứ
  // không được ném SyntaxError từ .json().
  let code = "internal";
  let message = `gateway trả ${response.status}`;
  let traceId: string | null = null;
  try {
    const body = (await response.json()) as { code?: string; message?: string; trace_id?: string | null };
    if (typeof body.code === "string") code = body.code;
    if (typeof body.message === "string") message = body.message;
    if (typeof body.trace_id === "string") traceId = body.trace_id;
  } catch {
    // Giữ nguyên message mặc định.
  }
  return new GatewayError(response.status, code, message, traceId);
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const env = getServerEnv();
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${env.gatewayToken}`);
  const response = await fetch(`${env.gatewayUrl}${path}`, {
    ...init,
    headers,
    // Trạng thái host và danh sách run đổi liên tục; một bản cache 30 giây ở đây
    // nghĩa là người vận hành nhìn thấy host đã chết vẫn xanh.
    cache: "no-store",
  });
  if (!response.ok) throw await toGatewayError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function runsQueryString(query: RunsQuery): string {
  const params = new URLSearchParams();
  if (query.trace_id) params.set("trace_id", query.trace_id);
  if (query.service) params.set("service", query.service);
  if (query.status) params.set("status", query.status);
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.offset !== undefined) params.set("offset", String(query.offset));
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export const gateway = {
  listHosts(): Promise<HostsResponse> {
    return call<HostsResponse>("/v1/hosts");
  },

  registerHost(registration: HostRegistration): Promise<HostState> {
    return call<HostState>("/v1/hosts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(registration),
    });
  },

  deleteHost(name: string): Promise<void> {
    // encodeURIComponent: tên host do người dùng gõ, có thể chứa "/" và làm
    // request rơi vào route khác.
    return call<void>(`/v1/hosts/${encodeURIComponent(name)}`, { method: "DELETE" });
  },

  listServices(): Promise<ServicesResponse> {
    return call<ServicesResponse>("/v1/services");
  },

  invokeUpload(service: string, file: File, modelVersion: string | null): Promise<InvokeResponse> {
    const form = new FormData();
    form.set("service", service);
    // Gửi chuỗi rỗng thì gateway coi là đã chọn model tên "" và bỏ qua
    // default_model của service — phải không set field mới đúng.
    if (modelVersion) form.set("model_version", modelVersion);
    form.set("file", file, file.name);
    // Cố tình KHÔNG đặt content-type: fetch phải tự sinh boundary của multipart.
    return call<InvokeResponse>("/v1/invoke/upload", { method: "POST", body: form });
  },

  listRuns(query: RunsQuery): Promise<RunsResponse> {
    return call<RunsResponse>(`/v1/runs${runsQueryString(query)}`);
  },

  getRun(runId: string): Promise<RunRecord> {
    return call<RunRecord>(`/v1/runs/${encodeURIComponent(runId)}`);
  },
};
```

- [ ] **Step 10: Chạy toàn bộ test, xác nhận xanh**

Run: `cd apps/dashboard && pnpm test && pnpm lint`
Expected: PASS — 33 test, `tsc` sạch.

- [ ] **Step 11: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard/src/lib apps/dashboard/tests/unit
git commit -m "feat(dashboard): client gateway phía server + kiểu dữ liệu hợp đồng"
```

---
### Task 3: Cổng mật khẩu — phiên ký HMAC, middleware chặn, trang đăng nhập

Không có task này thì BFF biến dashboard thành **proxy công khai** vào một gateway có xác thực: ai với tới cổng 3001 đều đọc được `/v1/hosts` và `POST` được host mới. Spec mục 9 đã ghi thẳng "Plan B2 làm điều này gắt hơn vì gateway phải với được từ nơi trình duyệt chạy".

Đây là mật khẩu **dùng chung**, không có khái niệm người dùng. Payload cookie chỉ chứa hạn dùng, nên mọi phiên hợp lệ là như nhau — đúng ý đồ, không phải thiếu sót.

**Files:**
- Create: `apps/dashboard/src/lib/session.ts`, `apps/dashboard/src/lib/guard.ts`, `apps/dashboard/src/middleware.ts`
- Create: `apps/dashboard/src/app/api/login/route.ts`, `apps/dashboard/src/app/api/logout/route.ts`, `apps/dashboard/src/app/login/page.tsx`, `apps/dashboard/src/components/LoginForm.tsx`
- Test: `apps/dashboard/tests/unit/session.test.ts`, `apps/dashboard/tests/unit/guard.test.ts`, `apps/dashboard/tests/unit/client-boundary.test.ts`

**Interfaces:**
- Consumes: `getServerEnv()` từ `@/lib/env` (Task 2).
- Produces:
  - `@/lib/session`: `SESSION_COOKIE = "vypq_session"`, `SESSION_TTL_MS`, `signSession(secret, expiresAtMs): Promise<string>`, `verifySession(secret, token, nowMs): Promise<boolean>`, `constantTimeEqual(a, b): boolean`.
  - `@/lib/guard`: `type GuardDecision`, `decideAccess(input): Promise<GuardDecision>`.

- [ ] **Step 1: Viết test thất bại cho `session.ts`**

`apps/dashboard/tests/unit/session.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { constantTimeEqual, signSession, verifySession } from "@/lib/session";

const SECRET = "bi-mat-phien";
const NOW = 1_760_000_000_000;
const EXPIRES = NOW + 60_000;

describe("signSession / verifySession", () => {
  it("nhận lại đúng cookie mình vừa ký", async () => {
    const token = await signSession(SECRET, EXPIRES);
    await expect(verifySession(SECRET, token, NOW)).resolves.toBe(true);
  });

  it("từ chối khi hạn đã qua", async () => {
    const token = await signSession(SECRET, EXPIRES);
    await expect(verifySession(SECRET, token, EXPIRES + 1)).resolves.toBe(false);
  });

  it("từ chối khi payload bị sửa để kéo dài hạn", async () => {
    // Đây là lý do tồn tại của chữ ký: payload nằm rõ ràng trong cookie.
    const token = await signSession(SECRET, EXPIRES);
    const signature = token.slice(token.lastIndexOf(".") + 1);
    await expect(verifySession(SECRET, `${EXPIRES + 999_999}.${signature}`, NOW)).resolves.toBe(false);
  });

  it("từ chối chữ ký ký bằng secret khác", async () => {
    const token = await signSession("secret-khac", EXPIRES);
    await expect(verifySession(SECRET, token, NOW)).resolves.toBe(false);
  });

  it("từ chối khi không có cookie", async () => {
    await expect(verifySession(SECRET, undefined, NOW)).resolves.toBe(false);
  });

  it.each(["", ".", "khongcodauchamnao", `${EXPIRES}.`, `.chuky`])(
    "từ chối cookie sai định dạng %j",
    async (token) => {
      await expect(verifySession(SECRET, token, NOW)).resolves.toBe(false);
    },
  );

  it("từ chối payload không phải số", async () => {
    const token = await signSession(SECRET, EXPIRES);
    const signature = token.slice(token.lastIndexOf(".") + 1);
    await expect(verifySession(SECRET, `mai-mai.${signature}`, NOW)).resolves.toBe(false);
  });
});

describe("constantTimeEqual", () => {
  it("đúng khi hai chuỗi giống hệt", () => {
    expect(constantTimeEqual("abcdef", "abcdef")).toBe(true);
  });

  it("sai khi khác nội dung", () => {
    expect(constantTimeEqual("abcdef", "abcdeg")).toBe(false);
  });

  it("sai khi khác độ dài, không ném", () => {
    expect(constantTimeEqual("abc", "abcdef")).toBe(false);
  });

  it("sai khi một bên rỗng — mật khẩu rỗng không được coi là khớp", () => {
    expect(constantTimeEqual("", "matkhau")).toBe(false);
  });
});
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/session.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/session"`.

- [ ] **Step 3: Viết `src/lib/session.ts`**

Dùng WebCrypto chứ không `node:crypto`: middleware của Next chạy trên Edge runtime, ở đó `node:crypto` không tồn tại.

```ts
export const SESSION_COOKIE = "vypq_session";

/** 12 giờ: đủ một ca làm việc, ngắn hơn thời gian thuê một máy GPU điển hình. */
export const SESSION_TTL_MS = 12 * 60 * 60 * 1000;

const encoder = new TextEncoder();

function base64url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function hmac(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return base64url(new Uint8Array(signature));
}

/**
 * So sánh không thoát sớm. Cùng lý do như `secrets.compare_digest` trong
 * gateway/auth.py: `===` dừng ở byte đầu khác nhau và làm rò rỉ độ dài tiền tố
 * đúng qua thời gian phản hồi.
 */
export function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function signSession(secret: string, expiresAtMs: number): Promise<string> {
  const payload = String(expiresAtMs);
  return `${payload}.${await hmac(secret, payload)}`;
}

export async function verifySession(
  secret: string,
  token: string | undefined,
  nowMs: number,
): Promise<boolean> {
  if (!token) return false;
  const separator = token.lastIndexOf(".");
  if (separator <= 0 || separator === token.length - 1) return false;
  const payload = token.slice(0, separator);
  const signature = token.slice(separator + 1);
  // Kiểm chữ ký TRƯỚC khi tin payload: đọc hạn ra rồi mới kiểm là mời người ta
  // tự ghi hạn cho mình.
  if (!constantTimeEqual(signature, await hmac(secret, payload))) return false;
  const expiresAt = Number(payload);
  return Number.isFinite(expiresAt) && nowMs < expiresAt;
}
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `cd apps/dashboard && pnpm test tests/unit/session.test.ts`
Expected: PASS — 15 test.

- [ ] **Step 5: Viết test thất bại cho `guard.ts`**

`apps/dashboard/tests/unit/guard.test.ts`:

```ts
import { beforeAll, describe, expect, it } from "vitest";

import { decideAccess } from "@/lib/guard";
import { signSession } from "@/lib/session";

const SECRET = "bi-mat-phien";
const NOW = 1_760_000_000_000;
let valid: string;

beforeAll(async () => {
  valid = await signSession(SECRET, NOW + 60_000);
});

describe("decideAccess", () => {
  it.each(["/login", "/api/login"])("cho %s đi qua khi chưa đăng nhập", async (pathname) => {
    const decision = await decideAccess({
      pathname, sessionToken: undefined, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("allow");
  });

  it("cho trang đã đăng nhập đi qua", async () => {
    const decision = await decideAccess({
      pathname: "/hosts", sessionToken: valid, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("allow");
  });

  it("đẩy trang chưa đăng nhập về /login", async () => {
    const decision = await decideAccess({
      pathname: "/hosts", sessionToken: undefined, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("redirect-login");
  });

  it("trả 401 cho API chứ không redirect — fetch() không đọc được trang HTML đăng nhập", async () => {
    const decision = await decideAccess({
      pathname: "/api/hosts", sessionToken: undefined, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("unauthorized-api");
  });

  it("chặn khi thiếu SESSION_SECRET thay vì cho qua", async () => {
    // Không có secret thì không kiểm được chữ ký nào cả. Mở cửa ở đây là biến
    // một lỗi cấu hình thành một dashboard không mật khẩu.
    const decision = await decideAccess({
      pathname: "/hosts", sessionToken: valid, sessionSecret: undefined, nowMs: NOW,
    });
    expect(decision.kind).toBe("misconfigured");
  });

  it("vẫn chặn /login khi thiếu secret — đăng nhập cũng không ký nổi cookie", async () => {
    const decision = await decideAccess({
      pathname: "/login", sessionToken: undefined, sessionSecret: undefined, nowMs: NOW,
    });
    expect(decision.kind).toBe("misconfigured");
  });

  it("đẩy về /login khi phiên hết hạn", async () => {
    const expired = await signSession(SECRET, NOW - 1);
    const decision = await decideAccess({
      pathname: "/hosts", sessionToken: expired, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("redirect-login");
  });

  it("không nhầm /loginhacker là đường công khai", async () => {
    const decision = await decideAccess({
      pathname: "/loginhacker", sessionToken: undefined, sessionSecret: SECRET, nowMs: NOW,
    });
    expect(decision.kind).toBe("redirect-login");
  });
});
```

- [ ] **Step 6: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/guard.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/guard"`.

- [ ] **Step 7: Viết `src/lib/guard.ts` và `src/middleware.ts`**

`src/lib/guard.ts`:

```ts
import { verifySession } from "@/lib/session";

export type GuardDecision =
  | { kind: "allow" }
  | { kind: "misconfigured" }
  | { kind: "unauthorized-api" }
  | { kind: "redirect-login" };

/** So khớp chính xác, không dùng startsWith: "/loginhacker" không phải "/login". */
const PUBLIC_PATHS = new Set(["/login", "/api/login"]);

export interface AccessInput {
  pathname: string;
  sessionToken: string | undefined;
  sessionSecret: string | undefined;
  nowMs: number;
}

export async function decideAccess(input: AccessInput): Promise<GuardDecision> {
  // Kiểm cấu hình TRƯỚC danh sách công khai: thiếu secret thì cả trang đăng nhập
  // cũng vô nghĩa (ký xong không ai kiểm được), nên nói thẳng lỗi cấu hình.
  if (!input.sessionSecret) return { kind: "misconfigured" };
  if (PUBLIC_PATHS.has(input.pathname)) return { kind: "allow" };
  if (await verifySession(input.sessionSecret, input.sessionToken, input.nowMs)) {
    return { kind: "allow" };
  }
  // fetch() từ client component không theo redirect sang HTML được — nó cần một
  // mã lỗi để hiện thông báo, nếu không sẽ parse trang đăng nhập như JSON.
  if (input.pathname.startsWith("/api/")) return { kind: "unauthorized-api" };
  return { kind: "redirect-login" };
}
```

`src/middleware.ts`:

```ts
import { NextResponse, type NextRequest } from "next/server";

import { decideAccess } from "@/lib/guard";
import { SESSION_COOKIE } from "@/lib/session";

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const decision = await decideAccess({
    pathname: request.nextUrl.pathname,
    sessionToken: request.cookies.get(SESSION_COOKIE)?.value,
    sessionSecret: process.env.SESSION_SECRET?.trim() || undefined,
    nowMs: Date.now(),
  });

  switch (decision.kind) {
    case "allow":
      return NextResponse.next();
    case "misconfigured":
      return NextResponse.json(
        { code: "internal", message: "SESSION_SECRET chưa được cấu hình", trace_id: null },
        { status: 500 },
      );
    case "unauthorized-api":
      return NextResponse.json(
        { code: "unauthorized", message: "phiên đã hết hạn, đăng nhập lại", trace_id: null },
        { status: 401 },
      );
    case "redirect-login": {
      const url = request.nextUrl.clone();
      url.pathname = "/login";
      url.search = "";
      return NextResponse.redirect(url);
    }
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 8: Chạy test, xác nhận xanh**

Run: `cd apps/dashboard && pnpm test tests/unit/guard.test.ts`
Expected: PASS — 10 test.

- [ ] **Step 9: Viết route đăng nhập/đăng xuất và trang đăng nhập**

`src/app/api/login/route.ts`:

```ts
import { NextResponse } from "next/server";

import { getServerEnv } from "@/lib/env";
import { SESSION_COOKIE, SESSION_TTL_MS, constantTimeEqual, signSession } from "@/lib/session";

export async function POST(request: Request): Promise<NextResponse> {
  const form = await request.formData();
  const password = String(form.get("password") ?? "");
  const env = getServerEnv();
  if (!constantTimeEqual(password, env.dashboardPassword)) {
    return NextResponse.json(
      { code: "unauthorized", message: "sai mật khẩu", trace_id: null },
      { status: 401 },
    );
  }
  const expiresAt = Date.now() + SESSION_TTL_MS;
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, await signSession(env.sessionSecret, expiresAt), {
    // httpOnly: JS trong trang không cần đọc cookie này, và không đọc được thì
    // XSS cũng không lấy đi được phiên.
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    expires: new Date(expiresAt),
  });
  return response;
}
```

`src/app/api/logout/route.ts`:

```ts
import { NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

export async function POST(): Promise<NextResponse> {
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0 });
  return response;
}
```

`src/components/LoginForm.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function LoginForm() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setPending(true);
    setError(null);
    const body = new FormData();
    body.set("password", password);
    const response = await fetch("/api/login", { method: "POST", body });
    setPending(false);
    if (!response.ok) {
      setError("Sai mật khẩu");
      return;
    }
    // replace chứ không push: nút Back không nên quay về trang đăng nhập.
    router.replace("/hosts");
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-lg font-semibold">vypq services</h1>
      <label className="block space-y-1">
        <span className="text-sm text-slate-600">Mật khẩu</span>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="w-full rounded border border-slate-300 px-3 py-2"
        />
      </label>
      {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : null}
      <button
        type="submit"
        disabled={pending || password.length === 0}
        className="w-full rounded bg-slate-900 px-3 py-2 text-white disabled:opacity-40"
      >
        {pending ? "Đang kiểm tra…" : "Đăng nhập"}
      </button>
    </form>
  );
}
```

`src/app/login/page.tsx`:

```tsx
import { LoginForm } from "@/components/LoginForm";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <LoginForm />
    </main>
  );
}
```

- [ ] **Step 10: Viết test canh ranh giới client/server**

Đây là bài kiểm tra kiến trúc, không phải kiểm tra hành vi: nó chặn đúng cái lỗi mà toàn bộ thiết kế BFF tồn tại để tránh.

`apps/dashboard/tests/unit/client-boundary.test.ts`:

```ts
import { readFileSync, readdirSync } from "node:fs";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("../../src", import.meta.url));

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return [".ts", ".tsx"].includes(extname(entry.name)) ? [full] : [];
  });
}

const files = sourceFiles(SRC).map((path) => ({ path, text: readFileSync(path, "utf8") }));
const clientFiles = files.filter((file) => /^\s*["']use client["']/m.test(file.text));

describe("ranh giới client/server", () => {
  it("có ít nhất một client component để phép kiểm này không rỗng", () => {
    expect(clientFiles.length).toBeGreaterThan(0);
  });

  it.each(["@/lib/gateway", "@/lib/env"])(
    "không client component nào import %s",
    (module) => {
      // Import từ client component sẽ kéo token gateway vào bundle trình duyệt.
      const offenders = clientFiles.filter((file) => file.text.includes(module)).map((file) => file.path);
      expect(offenders).toEqual([]);
    },
  );

  it("không file nào đặt token gateway vào biến NEXT_PUBLIC_", () => {
    // Mọi NEXT_PUBLIC_* đều được nhúng thẳng vào JS gửi cho trình duyệt.
    const offenders = files
      .filter((file) => /NEXT_PUBLIC_\w*(TOKEN|SECRET|PASSWORD)/.test(file.text))
      .map((file) => file.path);
    expect(offenders).toEqual([]);
  });

  it("không nơi nào gọi /v1/discovery/hosts — endpoint đó mang token của máy GPU", () => {
    const offenders = files.filter((file) => file.text.includes("discovery/hosts")).map((file) => file.path);
    expect(offenders).toEqual([]);
  });
});
```

- [ ] **Step 11: Chạy toàn bộ test và typecheck**

Run: `cd apps/dashboard && pnpm test && pnpm lint`
Expected: PASS — 62 test, `tsc` sạch.

- [ ] **Step 12: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard/src apps/dashboard/tests
git commit -m "feat(dashboard): cổng mật khẩu bằng cookie ký HMAC + canh ranh giới client/server"
```

---
### Task 4: Route Handler cho hosts và services

**Files:**
- Create: `apps/dashboard/src/lib/route-helpers.ts`, `apps/dashboard/src/app/api/hosts/route.ts`, `apps/dashboard/src/app/api/hosts/[name]/route.ts`, `apps/dashboard/src/app/api/services/route.ts`
- Test: `apps/dashboard/tests/unit/api-hosts.test.ts`

**Interfaces:**
- Consumes: `gateway` từ `@/lib/gateway`, `ApiError`/`GatewayError` từ `@/lib/errors` (Task 2).
- Produces: `respond<T>(fn: () => Promise<T>): Promise<NextResponse>` từ `@/lib/route-helpers`. Route `GET|POST /api/hosts`, `DELETE /api/hosts/{name}`, `GET /api/services`.

- [ ] **Step 1: Viết test thất bại**

`apps/dashboard/tests/unit/api-hosts.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GatewayError } from "@/lib/errors";

vi.mock("@/lib/gateway", () => ({
  gateway: {
    listHosts: vi.fn(),
    registerHost: vi.fn(),
    deleteHost: vi.fn(),
    listServices: vi.fn(),
  },
}));

const { gateway } = await import("@/lib/gateway");
const { GET, POST } = await import("@/app/api/hosts/route");
const { DELETE } = await import("@/app/api/hosts/[name]/route");
const { GET: getServices } = await import("@/app/api/services/route");

const mocked = gateway as unknown as Record<string, ReturnType<typeof vi.fn>>;

function jsonRequest(body: unknown): Request {
  return new Request("http://localhost:3001/api/hosts", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GET /api/hosts", () => {
  it("chuyển tiếp danh sách host", async () => {
    mocked.listHosts.mockResolvedValue({ hosts: [{ name: "a100" }] });
    const response = await GET();
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ hosts: [{ name: "a100" }] });
  });

  it("giữ nguyên mã lỗi gateway trả về", async () => {
    mocked.listHosts.mockRejectedValue(new GatewayError(503, "upstream_error", "gateway chết", "t1"));
    const response = await GET();
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      code: "upstream_error", message: "gateway chết", trace_id: "t1",
    });
  });

  it("không lộ chi tiết nội bộ khi lỗi không phải từ gateway", async () => {
    // Gateway tắt hẳn → fetch ném TypeError kèm stack và URL nội bộ. Trả nguyên
    // cái đó ra trình duyệt là rò rỉ topology.
    mocked.listHosts.mockRejectedValue(new TypeError("fetch failed: ECONNREFUSED 10.0.0.5:8080"));
    const response = await GET();
    expect(response.status).toBe(502);
    const body = (await response.json()) as { message: string };
    expect(body.message).toBe("không gọi được gateway");
    expect(JSON.stringify(body)).not.toContain("10.0.0.5");
  });
});

describe("POST /api/hosts", () => {
  it("đăng ký host hợp lệ và trả 201", async () => {
    mocked.registerHost.mockResolvedValue({ name: "a100", url: "https://x.ngrok.app" });
    const response = await POST(jsonRequest({ name: "a100", url: "https://x.ngrok.app", token: "bi-mat" }));
    expect(response.status).toBe(201);
    expect(mocked.registerHost).toHaveBeenCalledWith({
      name: "a100", url: "https://x.ngrok.app", token: "bi-mat",
    });
  });

  it("biến token rỗng thành null thay vì gửi chuỗi rỗng", async () => {
    // Gateway phân biệt "host không cần token" (null) với "token là chuỗi rỗng".
    mocked.registerHost.mockResolvedValue({ name: "a100", url: "https://x.ngrok.app" });
    await POST(jsonRequest({ name: "a100", url: "https://x.ngrok.app", token: "  " }));
    expect(mocked.registerHost).toHaveBeenCalledWith({
      name: "a100", url: "https://x.ngrok.app", token: null,
    });
  });

  it.each([
    [{ url: "https://x.ngrok.app" }, "thiếu name"],
    [{ name: "a100" }, "thiếu url"],
    [{ name: "  ", url: "https://x.ngrok.app" }, "name chỉ có khoảng trắng"],
  ])("từ chối %j (%s) với 422", async (body) => {
    const response = await POST(jsonRequest(body));
    expect(response.status).toBe(422);
    expect(mocked.registerHost).not.toHaveBeenCalled();
  });

  it.each(["file:///etc/passwd", "ftp://x", "khong-phai-url", "javascript:alert(1)"])(
    "từ chối URL %s vì poller chỉ gọi được http/https",
    async (url) => {
      const response = await POST(jsonRequest({ name: "a100", url }));
      expect(response.status).toBe(422);
      expect(mocked.registerHost).not.toHaveBeenCalled();
    },
  );

  it("trả 422 khi thân request không phải JSON hợp lệ", async () => {
    const request = new Request("http://localhost:3001/api/hosts", {
      method: "POST", headers: { "content-type": "application/json" }, body: "{",
    });
    const response = await POST(request);
    expect(response.status).toBe(422);
  });
});

describe("DELETE /api/hosts/[name]", () => {
  it("xoá host và trả 200 dù gateway trả 204 rỗng", async () => {
    mocked.deleteHost.mockResolvedValue(undefined);
    const response = await DELETE(new Request("http://localhost:3001/api/hosts/a100", { method: "DELETE" }), {
      params: Promise.resolve({ name: "a100" }),
    });
    expect(response.status).toBe(200);
    expect(mocked.deleteHost).toHaveBeenCalledWith("a100");
  });

  it("chuyển 404 của gateway ra nguyên vẹn", async () => {
    mocked.deleteHost.mockRejectedValue(new GatewayError(404, "bad_input", "không có host tên 'x'", null));
    const response = await DELETE(new Request("http://localhost:3001/api/hosts/x", { method: "DELETE" }), {
      params: Promise.resolve({ name: "x" }),
    });
    expect(response.status).toBe(404);
  });
});

describe("GET /api/services", () => {
  it("chuyển tiếp danh sách service", async () => {
    mocked.listServices.mockResolvedValue({ services: [] });
    const response = await getServices();
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ services: [] });
  });
});
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/api-hosts.test.ts`
Expected: FAIL — `Failed to resolve import "@/app/api/hosts/route"`.

- [ ] **Step 3: Viết `src/lib/route-helpers.ts`**

```ts
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
```

- [ ] **Step 4: Viết ba route handler**

`src/app/api/hosts/route.ts`:

```ts
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
```

`src/app/api/hosts/[name]/route.ts`:

```ts
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
```

`src/app/api/services/route.ts`:

```ts
import type { NextResponse } from "next/server";

import { gateway } from "@/lib/gateway";
import { respond } from "@/lib/route-helpers";

export function GET(): Promise<NextResponse> {
  return respond(() => gateway.listServices());
}
```

- [ ] **Step 5: Chạy test, xác nhận xanh**

Run: `cd apps/dashboard && pnpm test tests/unit/api-hosts.test.ts && pnpm lint`
Expected: PASS — 14 test.

- [ ] **Step 6: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard/src apps/dashboard/tests
git commit -m "feat(dashboard): route handler hosts/services + dịch lỗi không lộ nội bộ"
```

---

### Task 5: Khung giao diện + trang Model Hosts

Trang này là thứ người dùng mở đầu tiên sau khi thuê một máy GPU: dán URL ngrok + token vào, thấy nó chuyển xanh trong ~15 giây (một chu kỳ poll của gateway).

**Files:**
- Create: `apps/dashboard/src/components/ui.tsx`, `apps/dashboard/src/components/Nav.tsx`, `apps/dashboard/src/components/HostsPanel.tsx`, `apps/dashboard/src/app/hosts/page.tsx`
- Modify: `apps/dashboard/src/app/layout.tsx`
- Test: `apps/dashboard/tests/unit/hosts-panel.test.tsx`

**Interfaces:**
- Consumes: `HostState`, `ModelInfo` từ `@/lib/types`; `formatTimestamp`, `relativeTime` từ `@/lib/format`; route `/api/hosts` (Task 4).
- Produces: `Badge`, `Card`, `Button`, `TextField`, `EmptyState`, `DataTable` từ `@/components/ui`; `<HostsPanel hosts={HostState[]} />`.

- [ ] **Step 1: Viết test thất bại**

`apps/dashboard/tests/unit/hosts-panel.test.tsx`:

```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HostsPanel } from "@/components/HostsPanel";
import type { HostState } from "@/lib/types";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh, push: vi.fn(), replace: vi.fn() }) }));

const healthy: HostState = {
  name: "a100-vast",
  url: "https://abc.ngrok.app",
  healthy: true,
  models: [
    { id: "paddleocr-v4-vi", task: "ocr", kind: "opensource", runner: "paddle", loaded: true, available: true, vram_mb: 1200, base: null, trained_on: null },
    { id: "vietocr-ft-invoice", task: "ocr", kind: "finetuned", runner: "vietocr", loaded: false, available: false, vram_mb: 0, base: "vietocr-base", trained_on: "invoice-vi-v2" },
  ],
  last_seen_at: "2026-08-19T06:59:50Z",
  last_error: null,
};

const broken: HostState = {
  name: "may-cu",
  url: "https://cu.ngrok.app",
  healthy: false,
  models: [],
  last_seen_at: null,
  last_error: "ConnectTimeout sau 5s",
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  refresh.mockClear();
  fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HostsPanel", () => {
  it("hiện host khoẻ kèm model và thời điểm thấy lần cuối", () => {
    render(<HostsPanel hosts={[healthy]} />);
    const row = screen.getByRole("row", { name: /a100-vast/ });
    expect(within(row).getByText("khoẻ")).toBeInTheDocument();
    expect(within(row).getByText("paddleocr-v4-vi")).toBeInTheDocument();
  });

  it("đánh dấu model không dùng được thay vì giấu đi", () => {
    // Model thiếu checkpoint hay hết VRAM vẫn nằm trong /v1/models với
    // available=false; giấu nó đi thì người dùng không hiểu vì sao chọn không ra.
    render(<HostsPanel hosts={[healthy]} />);
    expect(screen.getByTitle(/không dùng được/)).toHaveTextContent("vietocr-ft-invoice");
  });

  it("phân biệt model fine-tune với model open-source", () => {
    render(<HostsPanel hosts={[healthy]} />);
    expect(screen.getByText("finetuned")).toBeInTheDocument();
  });

  it("hiện lỗi lần poll gần nhất của host đang chết", () => {
    render(<HostsPanel hosts={[broken]} />);
    const row = screen.getByRole("row", { name: /may-cu/ });
    expect(within(row).getByText("chết")).toBeInTheDocument();
    expect(within(row).getByText(/ConnectTimeout sau 5s/)).toBeInTheDocument();
  });

  it("nói rõ host mới đăng ký chưa từng được poll", () => {
    render(<HostsPanel hosts={[broken]} />);
    expect(screen.getByText("chưa từng")).toBeInTheDocument();
  });

  it("hiện hướng dẫn khi chưa có host nào", () => {
    render(<HostsPanel hosts={[]} />);
    expect(screen.getByText(/chưa cắm máy GPU nào/i)).toBeInTheDocument();
  });

  it("đăng ký host mới rồi làm mới dữ liệu trang", async () => {
    const user = userEvent.setup();
    render(<HostsPanel hosts={[]} />);
    await user.type(screen.getByLabelText("Tên"), "a100-vast");
    await user.type(screen.getByLabelText("URL"), "https://abc.ngrok.app");
    await user.type(screen.getByLabelText("Token"), "bi-mat");
    await user.click(screen.getByRole("button", { name: "Cắm host" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/hosts");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      name: "a100-vast", url: "https://abc.ngrok.app", token: "bi-mat",
    });
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  });

  it("hiện thông điệp lỗi của server thay vì im lặng", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ code: "bad_input", message: "URL phải là http hoặc https, không phải ftp:" }), { status: 422 }),
    );
    const user = userEvent.setup();
    render(<HostsPanel hosts={[]} />);
    await user.type(screen.getByLabelText("Tên"), "x");
    await user.type(screen.getByLabelText("URL"), "ftp://x");
    await user.click(screen.getByRole("button", { name: "Cắm host" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/URL phải là http hoặc https/);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("hỏi lại trước khi gỡ host — gỡ nhầm là cắt định tuyến của mọi service", async () => {
    const confirmSpy = vi.fn().mockReturnValue(false);
    vi.stubGlobal("confirm", confirmSpy);
    const user = userEvent.setup();
    render(<HostsPanel hosts={[healthy]} />);
    await user.click(screen.getByRole("button", { name: /gỡ a100-vast/i }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("gỡ host khi người dùng xác nhận", async () => {
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    const user = userEvent.setup();
    render(<HostsPanel hosts={[healthy]} />);
    await user.click(screen.getByRole("button", { name: /gỡ a100-vast/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/hosts/a100-vast");
    expect(init.method).toBe("DELETE");
  });
});
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/hosts-panel.test.tsx`
Expected: FAIL — `Failed to resolve import "@/components/HostsPanel"`.

- [ ] **Step 3: Viết `src/components/ui.tsx`**

```tsx
import type { ReactNode } from "react";

export type Tone = "ok" | "warn" | "bad" | "muted";

const TONE_CLASS: Record<Tone, string> = {
  ok: "bg-emerald-100 text-emerald-800",
  warn: "bg-amber-100 text-amber-800",
  bad: "bg-red-100 text-red-800",
  muted: "bg-slate-100 text-slate-600",
};

export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${TONE_CLASS[tone]}`}>
      {children}
    </span>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {title ? <h2 className="mb-3 text-sm font-semibold text-slate-700">{title}</h2> : null}
      {children}
    </section>
  );
}

export function Button({
  children, tone = "primary", ...rest
}: { children: ReactNode; tone?: "primary" | "danger" } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const base = tone === "danger" ? "border-red-300 text-red-700 hover:bg-red-50" : "bg-slate-900 text-white hover:bg-slate-700";
  return (
    <button {...rest} className={`rounded border px-3 py-1.5 text-sm disabled:opacity-40 ${base}`}>
      {children}
    </button>
  );
}

export function TextField({
  label, ...rest
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block space-y-1">
      <span className="text-sm text-slate-600">{label}</span>
      <input {...rest} className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm" />
    </label>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="rounded border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">{children}</p>;
}

export function DataTable({ headers, children }: { headers: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-slate-500">
          <tr>
            {headers.map((header) => (
              <th key={header} className="px-3 py-2 font-medium">{header}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Viết `src/components/Nav.tsx` và cập nhật layout**

`src/components/Nav.tsx`:

```tsx
import Link from "next/link";

const LINKS = [
  { href: "/hosts", label: "Model Hosts" },
  { href: "/services", label: "Services" },
  { href: "/playground", label: "Playground" },
  { href: "/runs", label: "Lịch sử" },
];

export function Nav() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <nav className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        <span className="font-semibold">vypq services</span>
        {LINKS.map((link) => (
          <Link key={link.href} href={link.href} className="text-sm text-slate-600 hover:text-slate-900">
            {link.label}
          </Link>
        ))}
        <form action="/api/logout" method="post" className="ml-auto">
          <button type="submit" className="text-sm text-slate-500 hover:text-slate-900">Đăng xuất</button>
        </form>
      </nav>
    </header>
  );
}
```

Sửa `src/app/layout.tsx`, thay thân `<body>`:

```tsx
      <body className="min-h-screen">
        <Nav />
        <main className="mx-auto max-w-6xl space-y-6 p-4">{children}</main>
      </body>
```

và thêm `import { Nav } from "@/components/Nav";` ở đầu file.

Trang `/login` cũng nằm dưới layout này nên sẽ có Nav — chấp nhận được vì các link đều bị middleware chặn về lại `/login`.

- [ ] **Step 5: Viết `src/components/HostsPanel.tsx`**

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge, Button, Card, DataTable, EmptyState, TextField } from "@/components/ui";
import { relativeTime } from "@/lib/format";
import type { HostState, ModelInfo } from "@/lib/types";

async function messageOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { message?: string };
    return body.message ?? `lỗi ${response.status}`;
  } catch {
    return `lỗi ${response.status}`;
  }
}

function ModelChip({ model }: { model: ModelInfo }) {
  return (
    <Badge
      tone={model.available ? (model.kind === "finetuned" ? "warn" : "muted") : "bad"}
      title={model.available ? `${model.kind} · ${model.runner}` : "không dùng được trên host này"}
    >
      {model.id}
    </Badge>
  );
}

export function HostsPanel({ hosts }: { hosts: HostState[] }) {
  const router = useRouter();
  // now cố định lúc render để relativeTime không phụ thuộc đồng hồ giữa các dòng.
  const now = Date.now();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function register(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setPending(true);
    setError(null);
    const response = await fetch("/api/hosts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, url, token }),
    });
    setPending(false);
    if (!response.ok) {
      setError(await messageOf(response));
      return;
    }
    setName("");
    setUrl("");
    setToken("");
    // Trang là Server Component; refresh() bắt server lấy lại danh sách host.
    router.refresh();
  }

  async function remove(hostName: string): Promise<void> {
    // Gỡ host = mọi service mất một đường định tuyến ngay lập tức. Đắt hơn
    // nhiều so với gõ lại, nên hỏi trước.
    if (!confirm(`Gỡ host "${hostName}"? Các service sẽ ngừng định tuyến vào máy này.`)) return;
    const response = await fetch(`/api/hosts/${encodeURIComponent(hostName)}`, { method: "DELETE" });
    if (!response.ok) {
      setError(await messageOf(response));
      return;
    }
    router.refresh();
  }

  return (
    <div className="space-y-6">
      <Card title="Cắm một máy GPU vừa thuê">
        <form onSubmit={register} className="grid gap-3 md:grid-cols-4 md:items-end">
          <TextField label="Tên" value={name} onChange={(e) => setName(e.target.value)} placeholder="a100-vast" />
          <TextField label="URL" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://abc.ngrok.app" />
          <TextField label="Token" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="VYPQ_MODEL_HOST_TOKEN" />
          <Button type="submit" disabled={pending || !name.trim() || !url.trim()}>
            {pending ? "Đang cắm…" : "Cắm host"}
          </Button>
        </form>
        {error ? <p role="alert" className="mt-3 text-sm text-red-600">{error}</p> : null}
        <p className="mt-3 text-xs text-slate-500">
          Gateway poll mỗi 15 giây và coi host là chết sau 45 giây không phản hồi — host mới cắm cần khoảng một chu kỳ để chuyển xanh.
        </p>
      </Card>

      <Card title="Host đang có">
        {hosts.length === 0 ? (
          <EmptyState>Chưa cắm máy GPU nào. Thuê máy, chạy model-host, mở ngrok rồi dán URL vào ô trên.</EmptyState>
        ) : (
          <DataTable headers={["Host", "Trạng thái", "Model", "Thấy lần cuối", ""]}>
            {hosts.map((host) => (
              <tr key={host.name}>
                <td className="px-3 py-2 align-top">
                  <div className="font-medium">{host.name}</div>
                  <div className="text-xs text-slate-500">{host.url}</div>
                </td>
                <td className="px-3 py-2 align-top">
                  <Badge tone={host.healthy ? "ok" : "bad"}>{host.healthy ? "khoẻ" : "chết"}</Badge>
                  {host.last_error ? <div className="mt-1 text-xs text-red-600">{host.last_error}</div> : null}
                </td>
                <td className="px-3 py-2 align-top">
                  {host.models.length === 0 ? (
                    <span className="text-xs text-slate-400">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {host.models.map((model) => <ModelChip key={model.id} model={model} />)}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 align-top text-xs text-slate-600">{relativeTime(host.last_seen_at, now)}</td>
                <td className="px-3 py-2 align-top">
                  <Button tone="danger" type="button" aria-label={`Gỡ ${host.name}`} onClick={() => void remove(host.name)}>
                    Gỡ
                  </Button>
                </td>
              </tr>
            ))}
          </DataTable>
        )}
      </Card>
    </div>
  );
}
```

`ModelChip` dùng `kind` để phân biệt fine-tune với open-source — đây là chỗ duy nhất trong dashboard cần biết sự khác nhau đó, và nó đến thẳng từ `models.yaml` của model-host.

- [ ] **Step 6: Viết `src/app/hosts/page.tsx`**

```tsx
import { HostsPanel } from "@/components/HostsPanel";
import { gateway } from "@/lib/gateway";

// Trang này phải phản ánh trạng thái ngay lúc mở; không có bản dựng tĩnh nào đúng.
export const dynamic = "force-dynamic";

export default async function HostsPage() {
  const { hosts } = await gateway.listHosts();
  return <HostsPanel hosts={hosts} />;
}
```

- [ ] **Step 7: Chạy test và typecheck**

Run: `cd apps/dashboard && pnpm test && pnpm lint`
Expected: PASS — 76 test, `tsc` sạch. Test `client-boundary` vẫn xanh (`HostsPanel` không import `@/lib/gateway`).

- [ ] **Step 8: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard/src apps/dashboard/tests
git commit -m "feat(dashboard): khung giao diện + trang Model Hosts"
```

---
### Task 6: `lib/capability.ts` + trang Services

Đây là task thực hiện yêu cầu spec §3.8: **service thứ ba chỉ cần trả đúng `/v1/info` là dùng được, không sửa code dashboard.** Mọi quyết định "dùng uploader nào, viewer nào" tập trung ở một file, và nhánh mặc định phải chạy được chứ không được ném.

**Files:**
- Create: `apps/dashboard/src/lib/capability.ts`, `apps/dashboard/src/components/ServicesTable.tsx`, `apps/dashboard/src/app/services/page.tsx`
- Test: `apps/dashboard/tests/unit/capability.test.ts`, `apps/dashboard/tests/unit/services-table.test.tsx`

**Interfaces:**
- Consumes: `ServiceState` từ `@/lib/types`; `formatTimestamp` từ `@/lib/format`; `Badge`/`Card`/`DataTable`/`EmptyState` từ `@/components/ui` (Task 5).
- Produces: `acceptForInput(capabilityInput: string): string`, `viewerFor(capabilityOutput: string): ViewerKind` với `type ViewerKind = "text_boxes" | "transcript" | "json"`, `isUsable(state: ServiceState): boolean`, `statusTone(status: HealthStatus): Tone`.

- [ ] **Step 1: Viết test thất bại cho `capability.ts`**

`apps/dashboard/tests/unit/capability.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { acceptForInput, isUsable, statusTone, viewerFor } from "@/lib/capability";
import type { ServiceState } from "@/lib/types";

describe("acceptForInput", () => {
  it("lọc theo ảnh cho service OCR", () => {
    expect(acceptForInput("image")).toBe("image/*");
  });

  it("lọc theo âm thanh cho service ASR", () => {
    expect(acceptForInput("audio")).toBe("audio/*");
  });

  it.each(["bytes", "video", "", "thu-gi-do-moi"])(
    "nhận mọi file khi chưa biết capability %j",
    (capability) => {
      // Spec §3.8: service thứ ba cắm vào phải dùng được ngay. Chặn upload vì
      // không nhận ra capability là biến "chưa hỗ trợ đẹp" thành "không dùng được".
      expect(acceptForInput(capability)).toBe("*/*");
    },
  );
});

describe("viewerFor", () => {
  it("chọn viewer bbox cho text_boxes", () => {
    expect(viewerFor("text_boxes")).toBe("text_boxes");
  });

  it("chọn viewer transcript cho transcript", () => {
    expect(viewerFor("transcript")).toBe("transcript");
  });

  it.each(["json", "embedding", ""])("rơi về xem JSON thô với %j", (capability) => {
    expect(viewerFor(capability)).toBe("json");
  });
});

const usable: ServiceState = {
  info: {
    name: "ocr", task: "ocr", capability_input: "image", capability_output: "text_boxes",
    version: "0.1.0", invoke_path: "/v1/ocr", default_model: "paddleocr-v4-vi",
  },
  base_url: "http://ocr:8000",
  status: "ok",
  last_seen_at: "2026-08-19T06:59:00Z",
};

describe("isUsable", () => {
  it("service khoẻ và đã biết info thì dùng được", () => {
    expect(isUsable(usable)).toBe(true);
  });

  it("info=null thì KHÔNG dùng được, dù trạng thái là gì", () => {
    // info=null nghĩa là gateway chưa từng poll được, nên chưa biết invoke_path.
    // Cho chọn ở playground = gửi request vào hư không.
    expect(isUsable({ ...usable, info: null, status: "ok" })).toBe(false);
  });

  it("service down thì không dùng được", () => {
    expect(isUsable({ ...usable, status: "down" })).toBe(false);
  });

  it("service degraded vẫn cho gọi — nó vẫn trả lời được", () => {
    expect(isUsable({ ...usable, status: "degraded" })).toBe(true);
  });
});

describe("statusTone", () => {
  it.each([
    ["ok", "ok"],
    ["degraded", "warn"],
    ["down", "bad"],
  ] as const)("ánh xạ %s sang tone %s", (status, tone) => {
    expect(statusTone(status)).toBe(tone);
  });
});
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/capability.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/capability"`.

- [ ] **Step 3: Viết `src/lib/capability.ts`**

```ts
import type { Tone } from "@/components/ui";
import type { HealthStatus, ServiceState } from "@/lib/types";

export type ViewerKind = "text_boxes" | "transcript" | "json";

/**
 * Đây là NƠI DUY NHẤT dashboard suy ra hành vi từ capability của service.
 * Spec §3.8: thêm service NER/TTS chỉ cần trả đúng /v1/info — nên mọi nhánh
 * không nhận ra đều phải có đường đi tiếp, không được ném.
 */
export function acceptForInput(capabilityInput: string): string {
  if (capabilityInput === "image") return "image/*";
  if (capabilityInput === "audio") return "audio/*";
  return "*/*";
}

export function viewerFor(capabilityOutput: string): ViewerKind {
  if (capabilityOutput === "text_boxes") return "text_boxes";
  if (capabilityOutput === "transcript") return "transcript";
  return "json";
}

/** Dùng được = đã biết cách gọi (info != null) và chưa bị coi là chết. */
export function isUsable(state: ServiceState): boolean {
  return state.info !== null && state.status !== "down";
}

export function statusTone(status: HealthStatus): Tone {
  if (status === "ok") return "ok";
  if (status === "degraded") return "warn";
  return "bad";
}
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `cd apps/dashboard && pnpm test tests/unit/capability.test.ts`
Expected: PASS — 17 test.

- [ ] **Step 5: Viết test thất bại cho `ServicesTable`**

`apps/dashboard/tests/unit/services-table.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ServicesTable } from "@/components/ServicesTable";
import type { ServiceState } from "@/lib/types";

const ocr: ServiceState = {
  info: {
    name: "ocr", task: "ocr", capability_input: "image", capability_output: "text_boxes",
    version: "0.1.0", invoke_path: "/v1/ocr", default_model: "paddleocr-v4-vi",
  },
  base_url: "http://ocr:8000",
  status: "ok",
  last_seen_at: "2026-08-19T06:59:00Z",
};

const unknown: ServiceState = {
  info: null,
  base_url: "http://ner:8000",
  status: "down",
  last_seen_at: null,
};

describe("ServicesTable", () => {
  it("hiện tên, task, capability và model mặc định của service đã biết", () => {
    render(<ServicesTable services={[ocr]} />);
    const row = screen.getByRole("row", { name: /ocr/ });
    expect(within(row).getByText("ocr")).toBeInTheDocument();
    expect(within(row).getByText("image → text_boxes")).toBeInTheDocument();
    expect(within(row).getByText("paddleocr-v4-vi")).toBeInTheDocument();
    expect(within(row).getByText("khoẻ")).toBeInTheDocument();
  });

  it("nói rõ chưa liên hệ được và KHÔNG đoán task khi info=null", () => {
    render(<ServicesTable services={[unknown]} />);
    const row = screen.getByRole("row", { name: /ner/ });
    expect(within(row).getByText(/chưa liên hệ được/i)).toBeInTheDocument();
    // Suy task từ base_url là chỗ dễ sai nhất: "ner" trong URL không phải task.
    expect(within(row).queryByText("ocr")).not.toBeInTheDocument();
    expect(within(row).queryByText("asr")).not.toBeInTheDocument();
  });

  it("hiện base_url để lần ra container nào đang hỏng", () => {
    render(<ServicesTable services={[unknown]} />);
    expect(screen.getByText("http://ner:8000")).toBeInTheDocument();
  });

  it("hiện hướng dẫn khi config/services.yaml chưa khai service nào", () => {
    render(<ServicesTable services={[]} />);
    expect(screen.getByText(/chưa khai service nào/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/services-table.test.tsx`
Expected: FAIL — `Failed to resolve import "@/components/ServicesTable"`.

- [ ] **Step 7: Viết `src/components/ServicesTable.tsx` và trang**

`src/components/ServicesTable.tsx`:

```tsx
import { Badge, Card, DataTable, EmptyState } from "@/components/ui";
import { statusTone } from "@/lib/capability";
import { formatTimestamp } from "@/lib/format";
import type { ServiceState } from "@/lib/types";

const STATUS_LABEL = { ok: "khoẻ", degraded: "chập chờn", down: "chết" } as const;

export function ServicesTable({ services }: { services: ServiceState[] }) {
  return (
    <Card title="Service đang đăng ký">
      {services.length === 0 ? (
        <EmptyState>Gateway chưa khai service nào — kiểm tra `config/services.yaml`.</EmptyState>
      ) : (
        <DataTable headers={["Service", "Task", "Capability", "Model mặc định", "Trạng thái", "Thấy lần cuối"]}>
          {services.map((state) => (
            <tr key={state.base_url}>
              <td className="px-3 py-2 align-top">
                <div className="font-medium">{state.info?.name ?? "—"}</div>
                <div className="text-xs text-slate-500">{state.base_url}</div>
                {state.info ? <div className="text-xs text-slate-400">v{state.info.version} · {state.info.invoke_path}</div> : null}
              </td>
              {state.info === null ? (
                // Một ô gộp thay vì rải "—": gateway chưa từng poll được service
                // này nên KHÔNG có gì để điền, và đoán vào đây là nói dối.
                <td className="px-3 py-2 align-top text-xs text-slate-500" colSpan={3}>
                  Chưa liên hệ được — gateway chưa đọc được /v1/info lần nào
                </td>
              ) : (
                <>
                  <td className="px-3 py-2 align-top">{state.info.task}</td>
                  <td className="px-3 py-2 align-top text-xs text-slate-600">
                    {state.info.capability_input} → {state.info.capability_output}
                  </td>
                  <td className="px-3 py-2 align-top text-xs">{state.info.default_model ?? "—"}</td>
                </>
              )}
              <td className="px-3 py-2 align-top">
                <Badge tone={statusTone(state.status)}>{STATUS_LABEL[state.status]}</Badge>
              </td>
              <td className="px-3 py-2 align-top text-xs text-slate-600">{formatTimestamp(state.last_seen_at)}</td>
            </tr>
          ))}
        </DataTable>
      )}
    </Card>
  );
}
```

`src/app/services/page.tsx`:

```tsx
import { ServicesTable } from "@/components/ServicesTable";
import { gateway } from "@/lib/gateway";

export const dynamic = "force-dynamic";

export default async function ServicesPage() {
  const { services } = await gateway.listServices();
  return <ServicesTable services={services} />;
}
```

- [ ] **Step 8: Chạy test và typecheck**

Run: `cd apps/dashboard && pnpm test && pnpm lint`
Expected: PASS — 97 test, `tsc` sạch.

- [ ] **Step 9: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard/src apps/dashboard/tests
git commit -m "feat(dashboard): suy uploader/viewer từ capability + trang Services"
```

---

### Task 7: Route Handler cho invoke và runs

**Files:**
- Create: `apps/dashboard/src/app/api/invoke/route.ts`, `apps/dashboard/src/app/api/runs/route.ts`, `apps/dashboard/src/app/api/runs/[runId]/route.ts`
- Test: `apps/dashboard/tests/unit/api-invoke.test.ts`

**Interfaces:**
- Consumes: `gateway`, `getServerEnv`, `ApiError`, `respond` (Tasks 2, 4).
- Produces: `POST /api/invoke` (multipart: `service`, `file`, `model_version?`) → `InvokeResponse`; `GET /api/runs?...` → `RunsResponse`; `GET /api/runs/{runId}` → `RunRecord`.

- [ ] **Step 1: Viết test thất bại**

`apps/dashboard/tests/unit/api-invoke.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GatewayError } from "@/lib/errors";

vi.mock("@/lib/gateway", () => ({
  gateway: { invokeUpload: vi.fn(), listRuns: vi.fn(), getRun: vi.fn() },
}));

const { gateway } = await import("@/lib/gateway");
const { POST } = await import("@/app/api/invoke/route");
const { GET: getRuns } = await import("@/app/api/runs/route");
const { GET: getRun } = await import("@/app/api/runs/[runId]/route");

const mocked = gateway as unknown as Record<string, ReturnType<typeof vi.fn>>;

function upload(fields: Record<string, string>, file?: File): Request {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.set(key, value);
  if (file) form.set("file", file, file.name);
  return new Request("http://localhost:3001/api/invoke", { method: "POST", body: form });
}

function smallFile(bytes = 8): File {
  return new File([new Uint8Array(bytes)], "hoadon.png", { type: "image/png" });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("GATEWAY_TOKEN", "token-gateway");
  vi.stubEnv("DASHBOARD_PASSWORD", "matkhau");
  vi.stubEnv("SESSION_SECRET", "bi-mat-phien");
});

describe("POST /api/invoke", () => {
  it("chuyển tiếp file và model_version xuống gateway", async () => {
    mocked.invokeUpload.mockResolvedValue({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} });
    const file = smallFile();
    const response = await POST(upload({ service: "ocr", model_version: "paddleocr-v4-vi" }, file));
    expect(response.status).toBe(200);
    expect(mocked.invokeUpload).toHaveBeenCalledWith("ocr", expect.any(File), "paddleocr-v4-vi");
  });

  it("truyền null khi không chọn model, để service dùng default_model", async () => {
    mocked.invokeUpload.mockResolvedValue({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} });
    await POST(upload({ service: "ocr", model_version: "" }, smallFile()));
    expect(mocked.invokeUpload).toHaveBeenCalledWith("ocr", expect.any(File), null);
  });

  it("từ chối khi thiếu service", async () => {
    const response = await POST(upload({}, smallFile()));
    expect(response.status).toBe(422);
    expect(mocked.invokeUpload).not.toHaveBeenCalled();
  });

  it("từ chối khi không đính kèm file", async () => {
    const response = await POST(upload({ service: "ocr" }));
    expect(response.status).toBe(422);
    expect(mocked.invokeUpload).not.toHaveBeenCalled();
  });

  it("chặn file quá 25 MB TRƯỚC khi gửi lên gateway", async () => {
    // Đẩy 200 MB qua gateway rồi để service từ chối là tốn băng thông và thời
    // gian của cả hai máy; chặn ở đây rẻ hơn và báo lỗi rõ hơn.
    const big = new File([new Uint8Array(25 * 1024 * 1024 + 1)], "to.wav", { type: "audio/wav" });
    const response = await POST(upload({ service: "asr" }, big));
    expect(response.status).toBe(413);
    expect(mocked.invokeUpload).not.toHaveBeenCalled();
    const body = (await response.json()) as { message: string };
    expect(body.message).toMatch(/25 MB/);
  });

  it("nhận file đúng bằng 25 MB", async () => {
    mocked.invokeUpload.mockResolvedValue({ trace_id: "t1", mode: "sync", run_id: "r1", result: {} });
    const exact = new File([new Uint8Array(25 * 1024 * 1024)], "vua-du.wav", { type: "audio/wav" });
    const response = await POST(upload({ service: "asr" }, exact));
    expect(response.status).toBe(200);
  });

  it("giữ nguyên 502 khi service lỗi thật", async () => {
    mocked.invokeUpload.mockRejectedValue(new GatewayError(502, "upstream_error", "service trả 500", "t9"));
    const response = await POST(upload({ service: "ocr" }, smallFile()));
    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toMatchObject({ code: "upstream_error", trace_id: "t9" });
  });
});

describe("GET /api/runs", () => {
  it("chuyển tiếp bộ lọc từ query string", async () => {
    mocked.listRuns.mockResolvedValue({ runs: [], total: 0 });
    await getRuns(new Request("http://localhost:3001/api/runs?service=ocr&status=failed&trace_id=t1&limit=10&offset=20"));
    expect(mocked.listRuns).toHaveBeenCalledWith({
      service: "ocr", status: "failed", trace_id: "t1", limit: 10, offset: 20,
    });
  });

  it("bỏ qua tham số rỗng thay vì gửi chuỗi rỗng xuống gateway", async () => {
    mocked.listRuns.mockResolvedValue({ runs: [], total: 0 });
    await getRuns(new Request("http://localhost:3001/api/runs?service=&status="));
    expect(mocked.listRuns).toHaveBeenCalledWith({ limit: 50, offset: 0 });
  });

  it("bỏ qua status không hợp lệ thay vì để gateway trả 422", async () => {
    mocked.listRuns.mockResolvedValue({ runs: [], total: 0 });
    await getRuns(new Request("http://localhost:3001/api/runs?status=khong-ton-tai"));
    expect(mocked.listRuns).toHaveBeenCalledWith({ limit: 50, offset: 0 });
  });

  it.each([
    ["limit=0", 1],
    ["limit=9999", 200],
    ["limit=abc", 50],
  ])("kẹp %s vào khoảng gateway chấp nhận", async (query, expected) => {
    mocked.listRuns.mockResolvedValue({ runs: [], total: 0 });
    await getRuns(new Request(`http://localhost:3001/api/runs?${query}`));
    expect(mocked.listRuns).toHaveBeenCalledWith(expect.objectContaining({ limit: expected }));
  });

  it("không cho offset âm", async () => {
    mocked.listRuns.mockResolvedValue({ runs: [], total: 0 });
    await getRuns(new Request("http://localhost:3001/api/runs?offset=-5"));
    expect(mocked.listRuns).toHaveBeenCalledWith(expect.objectContaining({ offset: 0 }));
  });
});

describe("GET /api/runs/[runId]", () => {
  it("trả run theo id", async () => {
    mocked.getRun.mockResolvedValue({ id: "r1" });
    const response = await getRun(new Request("http://localhost:3001/api/runs/r1"), {
      params: Promise.resolve({ runId: "r1" }),
    });
    expect(response.status).toBe(200);
    expect(mocked.getRun).toHaveBeenCalledWith("r1");
  });

  it("chuyển 404 ra nguyên vẹn", async () => {
    mocked.getRun.mockRejectedValue(new GatewayError(404, "bad_input", "không có run 'x'", null));
    const response = await getRun(new Request("http://localhost:3001/api/runs/x"), {
      params: Promise.resolve({ runId: "x" }),
    });
    expect(response.status).toBe(404);
  });
});
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/api-invoke.test.ts`
Expected: FAIL — `Failed to resolve import "@/app/api/invoke/route"`.

- [ ] **Step 3: Viết ba route handler**

`src/app/api/invoke/route.ts`:

```ts
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
```

`src/app/api/runs/route.ts`:

```ts
import type { NextResponse } from "next/server";

import { gateway } from "@/lib/gateway";
import { respond } from "@/lib/route-helpers";
import type { RunStatus, RunsQuery } from "@/lib/types";

const STATUSES: readonly RunStatus[] = ["pending", "ok", "failed"];

/** Giữ đúng khoảng gateway chấp nhận (limit 1..200, offset ≥ 0). */
function clamp(raw: string | null, fallback: number, min: number, max: number): number {
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

export function GET(request: Request): Promise<NextResponse> {
  return respond(() => {
    const params = new URL(request.url).searchParams;
    const query: RunsQuery = {
      limit: clamp(params.get("limit"), 50, 1, 200),
      offset: clamp(params.get("offset"), 0, 0, Number.MAX_SAFE_INTEGER),
    };
    const traceId = params.get("trace_id")?.trim();
    const service = params.get("service")?.trim();
    const status = params.get("status")?.trim();
    if (traceId) query.trace_id = traceId;
    if (service) query.service = service;
    // Lọc ở đây chứ không đẩy xuống: gateway trả 422 cho status lạ, và một
    // đường dẫn cũ bị bookmark sẽ biến thành trang lỗi thay vì danh sách.
    if (status && (STATUSES as readonly string[]).includes(status)) {
      query.status = status as RunStatus;
    }
    return gateway.listRuns(query);
  });
}
```

`src/app/api/runs/[runId]/route.ts`:

```ts
import type { NextResponse } from "next/server";

import { gateway } from "@/lib/gateway";
import { respond } from "@/lib/route-helpers";

export function GET(
  _request: Request,
  context: { params: Promise<{ runId: string }> },
): Promise<NextResponse> {
  return respond(async () => gateway.getRun((await context.params).runId));
}
```

- [ ] **Step 4: Chạy test và typecheck**

Run: `cd apps/dashboard && pnpm test && pnpm lint`
Expected: PASS — 116 test, `tsc` sạch.

- [ ] **Step 5: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard/src apps/dashboard/tests
git commit -m "feat(dashboard): route handler invoke (chặn 25 MB) và runs"
```

---
### Task 8: Viewer kết quả — overlay bbox cho OCR, transcript cho ASR

**Ràng buộc quan trọng, đọc kỹ:** `SyncProxy.invoke` ghi `input_uri = null`, nên **trang chi tiết run không có ảnh gốc**. `OcrViewer` bắt buộc phải vẽ được bbox khi `imageUrl === null` — dùng khung toạ độ suy ra từ chính các polygon. Chỉ playground (đang cầm file trong trình duyệt) mới truyền được `imageUrl`.

Cách canh overlay: `<svg>` phủ tuyệt đối lên `<img>`, cả hai chiếm đúng một khung; `viewBox` đặt bằng kích thước tự nhiên của ảnh (lấy khi `onLoad`) nên toạ độ polygon dùng thẳng, không nhân chia. Vì tỉ lệ khung và tỉ lệ `viewBox` bằng nhau, `preserveAspectRatio` mặc định canh đúng.

**Files:**
- Create: `apps/dashboard/src/lib/results.ts`, `apps/dashboard/src/components/viewers/OcrViewer.tsx`, `apps/dashboard/src/components/viewers/AsrViewer.tsx`, `apps/dashboard/src/components/viewers/ResultViewer.tsx`
- Test: `apps/dashboard/tests/unit/results.test.ts`, `apps/dashboard/tests/unit/viewers.test.tsx`

**Interfaces:**
- Consumes: `OcrResult`, `AsrResult`, `TextBox`, `Segment` từ `@/lib/types`; `viewerFor` từ `@/lib/capability`; `formatClock` từ `@/lib/format`.
- Produces: `asOcrResult(output: unknown): OcrResult | null`, `asAsrResult(output: unknown): AsrResult | null`, `boundingExtent(boxes: TextBox[]): { width: number; height: number }` từ `@/lib/results`; `<OcrViewer result imageUrl />`, `<AsrViewer result audioUrl onSeek />`, `<ResultViewer capabilityOutput output imageUrl audioUrl />`.

- [ ] **Step 1: Viết test thất bại cho `results.ts`**

`apps/dashboard/tests/unit/results.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { asAsrResult, asOcrResult, boundingExtent } from "@/lib/results";

const box = { id: 1, polygon: [[0, 0], [10, 0], [10, 5], [0, 5]], text: "HOÁ ĐƠN", confidence: 0.98, ignore: false };

describe("asOcrResult", () => {
  it("nhận kết quả OCR hợp lệ", () => {
    const parsed = asOcrResult({ full_text: "HOÁ ĐƠN", boxes: [box] });
    expect(parsed?.boxes).toHaveLength(1);
    expect(parsed?.full_text).toBe("HOÁ ĐƠN");
  });

  it("nhận kết quả rỗng — ảnh không có chữ là kết quả hợp lệ", () => {
    expect(asOcrResult({ full_text: "", boxes: [] })).toEqual({ full_text: "", boxes: [] });
  });

  it("bù full_text rỗng khi service không trả trường đó", () => {
    expect(asOcrResult({ boxes: [box] })?.full_text).toBe("");
  });

  it("bỏ box có polygon dưới 4 điểm thay vì vẽ hình méo", () => {
    const parsed = asOcrResult({ full_text: "x", boxes: [box, { ...box, id: 2, polygon: [[0, 0], [1, 1]] }] });
    expect(parsed?.boxes.map((b) => b.id)).toEqual([1]);
  });

  it("bỏ box có toạ độ không phải số", () => {
    const parsed = asOcrResult({ full_text: "x", boxes: [{ ...box, id: 3, polygon: [["a", 0], [1, 1], [2, 2], [3, 3]] }] });
    expect(parsed?.boxes).toEqual([]);
  });

  it.each([null, undefined, 42, "chuoi", { segments: [] }])(
    "trả null cho payload không phải OCR: %j",
    (payload) => {
      // ResultViewer dựa vào null này để rơi về xem JSON thô thay vì hiện trang trắng.
      expect(asOcrResult(payload)).toBeNull();
    },
  );
});

describe("asAsrResult", () => {
  it("nhận transcript hợp lệ", () => {
    const parsed = asAsrResult({ text: "xin chào", segments: [{ start: 0, end: 1.5, text: "xin chào", speaker: "A" }] });
    expect(parsed?.segments).toHaveLength(1);
    expect(parsed?.segments[0]?.speaker).toBe("A");
  });

  it("bù speaker null khi model không tách người nói", () => {
    const parsed = asAsrResult({ text: "a", segments: [{ start: 0, end: 1, text: "a" }] });
    expect(parsed?.segments[0]?.speaker).toBeNull();
  });

  it("bỏ segment có mốc thời gian không phải số", () => {
    const parsed = asAsrResult({ text: "a", segments: [{ start: "x", end: 1, text: "a" }] });
    expect(parsed?.segments).toEqual([]);
  });

  it.each([null, 42, { boxes: [] }])("trả null cho payload không phải ASR: %j", (payload) => {
    expect(asAsrResult(payload)).toBeNull();
  });
});

describe("boundingExtent", () => {
  it("bao trọn mọi polygon", () => {
    expect(boundingExtent([box, { ...box, id: 2, polygon: [[0, 0], [40, 0], [40, 30], [0, 30]] }]))
      .toEqual({ width: 40, height: 30 });
  });

  it("trả khung tối thiểu khi không có box — svg viewBox 0×0 không hiển thị được", () => {
    expect(boundingExtent([])).toEqual({ width: 1, height: 1 });
  });

  it("bỏ qua toạ độ âm chứ không để viewBox nhỏ hơn 1", () => {
    expect(boundingExtent([{ ...box, polygon: [[-5, -5], [-1, -5], [-1, -1], [-5, -1]] }]))
      .toEqual({ width: 1, height: 1 });
  });
});
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/results.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/results"`.

- [ ] **Step 3: Viết `src/lib/results.ts`**

```ts
import type { AsrResult, OcrResult, Polygon, Segment, TextBox } from "@/lib/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toPolygon(value: unknown): Polygon | null {
  if (!Array.isArray(value) || value.length < 4) return null;
  const points: Polygon = [];
  for (const point of value) {
    if (!Array.isArray(point) || point.length < 2) return null;
    const [x, y] = point;
    if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) {
      return null;
    }
    points.push([x, y]);
  }
  return points;
}

function toTextBox(value: unknown, index: number): TextBox | null {
  if (!isRecord(value)) return null;
  const polygon = toPolygon(value.polygon);
  if (!polygon) return null;
  return {
    id: typeof value.id === "number" ? value.id : index,
    polygon,
    text: typeof value.text === "string" ? value.text : "",
    confidence: typeof value.confidence === "number" ? value.confidence : null,
    ignore: value.ignore === true,
  };
}

/**
 * Đọc `RunRecord.output` — thứ gateway lưu nguyên si từ service. Service là code
 * của mình nhưng model-host thì có thể là bản mới hơn, nên payload lệch hợp đồng
 * phải rơi về `null` để ResultViewer hiện JSON thô, thay vì làm trang trắng.
 */
export function asOcrResult(output: unknown): OcrResult | null {
  if (!isRecord(output)) return null;
  if (!Array.isArray(output.boxes)) return null;
  const boxes = output.boxes.map(toTextBox).filter((box): box is TextBox => box !== null);
  return { full_text: typeof output.full_text === "string" ? output.full_text : "", boxes };
}

function toSegment(value: unknown): Segment | null {
  if (!isRecord(value)) return null;
  const { start, end } = value;
  if (typeof start !== "number" || typeof end !== "number") return null;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return {
    start,
    end,
    text: typeof value.text === "string" ? value.text : "",
    speaker: typeof value.speaker === "string" ? value.speaker : null,
  };
}

export function asAsrResult(output: unknown): AsrResult | null {
  if (!isRecord(output)) return null;
  if (!Array.isArray(output.segments)) return null;
  const segments = output.segments.map(toSegment).filter((seg): seg is Segment => seg !== null);
  return { text: typeof output.text === "string" ? output.text : "", segments };
}

/**
 * Khung toạ độ dùng khi KHÔNG có ảnh gốc (mọi run sync đều ghi input_uri=null).
 * Tối thiểu 1×1: svg viewBox có chiều bằng 0 thì không vẽ ra gì cả.
 */
export function boundingExtent(boxes: TextBox[]): { width: number; height: number } {
  let width = 1;
  let height = 1;
  for (const box of boxes) {
    for (const [x, y] of box.polygon) {
      if (x > width) width = x;
      if (y > height) height = y;
    }
  }
  return { width, height };
}
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `cd apps/dashboard && pnpm test tests/unit/results.test.ts`
Expected: PASS — 19 test.

- [ ] **Step 5: Viết test thất bại cho các viewer**

`apps/dashboard/tests/unit/viewers.test.tsx`:

```tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AsrViewer } from "@/components/viewers/AsrViewer";
import { OcrViewer } from "@/components/viewers/OcrViewer";
import { ResultViewer } from "@/components/viewers/ResultViewer";
import type { AsrResult, OcrResult } from "@/lib/types";

const ocr: OcrResult = {
  full_text: "HOÁ ĐƠN\nTổng cộng 120000",
  boxes: [
    { id: 1, polygon: [[10, 10], [110, 10], [110, 40], [10, 40]], text: "HOÁ ĐƠN", confidence: 0.98, ignore: false },
    { id: 2, polygon: [[10, 50], [200, 50], [200, 80], [10, 80]], text: "Tổng cộng 120000", confidence: 0.71, ignore: false },
    { id: 3, polygon: [[0, 90], [20, 90], [20, 100], [0, 100]], text: "nhiễu", confidence: 0.2, ignore: true },
  ],
};

const asr: AsrResult = {
  text: "xin chào các bạn",
  segments: [
    { start: 0, end: 1.5, text: "xin chào", speaker: "A" },
    { start: 1.5, end: 3.25, text: "các bạn", speaker: "B" },
  ],
};

describe("OcrViewer", () => {
  it("vẽ một polygon cho mỗi box", () => {
    const { container } = render(<OcrViewer result={ocr} imageUrl={null} />);
    expect(container.querySelectorAll("svg polygon")).toHaveLength(3);
  });

  it("dùng toạ độ gốc làm điểm của polygon, không tự nhân tỉ lệ", () => {
    const { container } = render(<OcrViewer result={ocr} imageUrl={null} />);
    const first = container.querySelector("svg polygon");
    expect(first?.getAttribute("points")).toBe("10,10 110,10 110,40 10,40");
  });

  it("khi không có ảnh thì viewBox suy từ chính các box", () => {
    // Đây là đường đi của trang chi tiết run: run sync ghi input_uri=null.
    const { container } = render(<OcrViewer result={ocr} imageUrl={null} />);
    expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 200 100");
  });

  it("khi có ảnh thì viewBox theo kích thước tự nhiên của ảnh", () => {
    const { container } = render(<OcrViewer result={ocr} imageUrl="blob:hoadon" />);
    const image = screen.getByRole("img", { name: /ảnh đầu vào/i });
    Object.defineProperty(image, "naturalWidth", { value: 1240, configurable: true });
    Object.defineProperty(image, "naturalHeight", { value: 1754, configurable: true });
    fireEvent.load(image);
    expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 1240 1754");
  });

  it("liệt kê text của từng box kèm độ tin cậy", () => {
    render(<OcrViewer result={ocr} imageUrl={null} />);
    const row = screen.getByRole("row", { name: /HOÁ ĐƠN/ });
    expect(within(row).getByText("0.98")).toBeInTheDocument();
  });

  it("đánh dấu box bị bỏ qua thay vì giấu", () => {
    render(<OcrViewer result={ocr} imageUrl={null} />);
    expect(screen.getByRole("row", { name: /nhiễu/ })).toHaveAttribute("data-ignored", "true");
  });

  it("làm nổi polygon tương ứng khi rê vào một dòng text", async () => {
    const user = userEvent.setup();
    const { container } = render(<OcrViewer result={ocr} imageUrl={null} />);
    await user.hover(screen.getByRole("row", { name: /Tổng cộng 120000/ }));
    const selected = container.querySelectorAll('svg polygon[data-selected="true"]');
    expect(selected).toHaveLength(1);
    expect(selected[0]?.getAttribute("points")).toBe("10,50 200,50 200,80 10,80");
  });

  it("hiện toàn văn để copy", () => {
    render(<OcrViewer result={ocr} imageUrl={null} />);
    expect(screen.getByText(/Tổng cộng 120000/)).toBeInTheDocument();
  });

  it("nói rõ khi model không tìm thấy chữ nào", () => {
    render(<OcrViewer result={{ full_text: "", boxes: [] }} imageUrl={null} />);
    expect(screen.getByText(/không tìm thấy chữ nào/i)).toBeInTheDocument();
  });
});

describe("AsrViewer", () => {
  it("liệt kê từng segment kèm mốc thời gian và người nói", () => {
    render(<AsrViewer result={asr} audioUrl={null} onSeek={vi.fn()} />);
    const row = screen.getByRole("row", { name: /các bạn/ });
    expect(within(row).getByText("00:01.5 → 00:03.2")).toBeInTheDocument();
    expect(within(row).getByText("B")).toBeInTheDocument();
  });

  it("hiện toàn văn transcript", () => {
    render(<AsrViewer result={asr} audioUrl={null} onSeek={vi.fn()} />);
    expect(screen.getByText("xin chào các bạn")).toBeInTheDocument();
  });

  it("gọi onSeek với mốc bắt đầu khi bấm vào segment", async () => {
    const onSeek = vi.fn();
    const user = userEvent.setup();
    render(<AsrViewer result={asr} audioUrl="blob:am-thanh" onSeek={onSeek} />);
    await user.click(screen.getByRole("button", { name: /nghe từ 00:01.5/i }));
    expect(onSeek).toHaveBeenCalledWith(1.5);
  });

  it("không hiện nút nghe khi không có file âm thanh (trang lịch sử)", () => {
    render(<AsrViewer result={asr} audioUrl={null} onSeek={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /nghe từ/i })).not.toBeInTheDocument();
  });

  it("nói rõ khi model không nghe ra gì", () => {
    render(<AsrViewer result={{ text: "", segments: [] }} audioUrl={null} onSeek={vi.fn()} />);
    expect(screen.getByText(/không nhận ra lời nào/i)).toBeInTheDocument();
  });
});

describe("ResultViewer", () => {
  it("chọn viewer bbox theo capability text_boxes", () => {
    const { container } = render(
      <ResultViewer capabilityOutput="text_boxes" output={ocr as unknown as Record<string, unknown>} imageUrl={null} audioUrl={null} />,
    );
    expect(container.querySelectorAll("svg polygon")).toHaveLength(3);
  });

  it("chọn viewer transcript theo capability transcript", () => {
    render(
      <ResultViewer capabilityOutput="transcript" output={asr as unknown as Record<string, unknown>} imageUrl={null} audioUrl={null} />,
    );
    expect(screen.getByText("xin chào các bạn")).toBeInTheDocument();
  });

  it("hiện JSON thô cho capability chưa biết — service thứ ba cắm vào vẫn xem được", () => {
    render(
      <ResultViewer capabilityOutput="embedding" output={{ vector: [0.1, 0.2] }} imageUrl={null} audioUrl={null} />,
    );
    expect(screen.getByText(/"vector"/)).toBeInTheDocument();
  });

  it("rơi về JSON thô khi payload không khớp capability đã khai", () => {
    // Model-host bản mới đổi hình dạng output là chuyện xảy ra được; hiện thô
    // vẫn hơn trang trắng.
    render(
      <ResultViewer capabilityOutput="text_boxes" output={{ khong_phai_boxes: 1 }} imageUrl={null} audioUrl={null} />,
    );
    expect(screen.getByText(/khong_phai_boxes/)).toBeInTheDocument();
  });

  it("nói rõ khi run chưa có output", () => {
    // Run async lúc mới nhận, và mọi run failed, đều có output=null.
    render(<ResultViewer capabilityOutput="text_boxes" output={null} imageUrl={null} audioUrl={null} />);
    expect(screen.getByText(/chưa có kết quả/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/viewers.test.tsx`
Expected: FAIL — `Failed to resolve import "@/components/viewers/OcrViewer"`.

- [ ] **Step 7: Viết `src/components/viewers/OcrViewer.tsx`**

```tsx
"use client";

import { useState } from "react";

import { DataTable, EmptyState } from "@/components/ui";
import { boundingExtent } from "@/lib/results";
import type { OcrResult } from "@/lib/types";

function pointsOf(polygon: [number, number][]): string {
  return polygon.map(([x, y]) => `${x},${y}`).join(" ");
}

export function OcrViewer({ result, imageUrl }: { result: OcrResult; imageUrl: string | null }) {
  // Kích thước thật của ảnh chỉ biết sau khi trình duyệt tải xong. Trước đó,
  // và trong mọi trường hợp không có ảnh, dùng khung suy từ chính các polygon.
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const frame = natural ?? boundingExtent(result.boxes);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="relative w-full self-start overflow-hidden rounded border border-slate-200 bg-white">
        {imageUrl ? (
          <img
            src={imageUrl}
            alt="Ảnh đầu vào"
            className="block h-auto w-full"
            onLoad={(event) =>
              setNatural({
                width: event.currentTarget.naturalWidth || 1,
                height: event.currentTarget.naturalHeight || 1,
              })
            }
          />
        ) : (
          // Không có ảnh (mọi run sync ghi input_uri=null): giữ đúng tỉ lệ khung
          // toạ độ để bố cục các box vẫn đọc được.
          <div style={{ paddingBottom: `${(frame.height / frame.width) * 100}%` }} />
        )}
        <svg
          viewBox={`0 0 ${frame.width} ${frame.height}`}
          className="absolute inset-0 h-full w-full"
          aria-label="Vùng chữ model tìm được"
        >
          {result.boxes.map((box) => (
            <polygon
              key={box.id}
              points={pointsOf(box.polygon)}
              data-selected={selected === box.id}
              className={
                selected === box.id
                  ? "fill-amber-400/30 stroke-amber-600"
                  : box.ignore
                    ? "fill-none stroke-slate-400"
                    : "fill-emerald-400/10 stroke-emerald-600"
              }
              // vectorEffect: nét vẫn 1px sau khi svg co giãn theo khung ảnh.
              vectorEffect="non-scaling-stroke"
              strokeWidth={1.5}
            />
          ))}
        </svg>
      </div>

      <div className="space-y-3">
        {result.boxes.length === 0 ? (
          <EmptyState>Model không tìm thấy chữ nào trong ảnh này.</EmptyState>
        ) : (
          <DataTable headers={["#", "Text", "Độ tin cậy"]}>
            {result.boxes.map((box) => (
              <tr
                key={box.id}
                data-ignored={box.ignore}
                onMouseEnter={() => setSelected(box.id)}
                onMouseLeave={() => setSelected(null)}
                className={box.ignore ? "text-slate-400" : "cursor-default hover:bg-amber-50"}
              >
                <td className="px-3 py-1.5">{box.id}</td>
                <td className="px-3 py-1.5">{box.text}</td>
                <td className="px-3 py-1.5 text-xs">{box.confidence === null ? "—" : box.confidence.toFixed(2)}</td>
              </tr>
            ))}
          </DataTable>
        )}
        <details className="rounded border border-slate-200 bg-white p-3">
          <summary className="cursor-pointer text-sm text-slate-600">Toàn văn</summary>
          <pre className="mt-2 whitespace-pre-wrap text-sm">{result.full_text}</pre>
        </details>
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Viết `src/components/viewers/AsrViewer.tsx`**

```tsx
"use client";

import { DataTable, EmptyState } from "@/components/ui";
import { formatClock } from "@/lib/format";
import type { AsrResult } from "@/lib/types";

/**
 * `onSeek` do component cha cung cấp thay vì tự giữ ref tới <audio>: playground
 * sở hữu phần tử audio (nó cũng sở hữu object URL của file), còn trang lịch sử
 * không có audio nào để tua.
 */
export function AsrViewer({
  result,
  audioUrl,
  onSeek,
}: {
  result: AsrResult;
  audioUrl: string | null;
  onSeek: (seconds: number) => void;
}) {
  if (result.segments.length === 0 && result.text.length === 0) {
    return <EmptyState>Model không nhận ra lời nào trong file này.</EmptyState>;
  }

  return (
    <div className="space-y-3">
      <div className="rounded border border-slate-200 bg-white p-3">
        <p className="whitespace-pre-wrap text-sm">{result.text}</p>
      </div>
      {result.segments.length === 0 ? null : (
        <DataTable headers={["Thời gian", "Người nói", "Nội dung", ""]}>
          {result.segments.map((segment, index) => (
            <tr key={`${segment.start}-${index}`}>
              <td className="whitespace-nowrap px-3 py-1.5 text-xs text-slate-600">
                {formatClock(segment.start)} → {formatClock(segment.end)}
              </td>
              <td className="px-3 py-1.5 text-xs">{segment.speaker ?? "—"}</td>
              <td className="px-3 py-1.5">{segment.text}</td>
              <td className="px-3 py-1.5">
                {audioUrl ? (
                  <button
                    type="button"
                    aria-label={`Nghe từ ${formatClock(segment.start)}`}
                    onClick={() => onSeek(segment.start)}
                    className="text-xs text-slate-500 hover:text-slate-900"
                  >
                    ▶
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </DataTable>
      )}
    </div>
  );
}
```

- [ ] **Step 9: Viết `src/components/viewers/ResultViewer.tsx`**

```tsx
"use client";

import { AsrViewer } from "@/components/viewers/AsrViewer";
import { OcrViewer } from "@/components/viewers/OcrViewer";
import { EmptyState } from "@/components/ui";
import { viewerFor } from "@/lib/capability";
import { asAsrResult, asOcrResult } from "@/lib/results";

function RawJson({ output }: { output: unknown }) {
  return (
    <pre className="overflow-x-auto rounded border border-slate-200 bg-white p-3 text-xs">
      {JSON.stringify(output, null, 2)}
    </pre>
  );
}

export function ResultViewer({
  capabilityOutput,
  output,
  imageUrl,
  audioUrl,
  onSeek,
}: {
  capabilityOutput: string;
  output: Record<string, unknown> | null;
  imageUrl: string | null;
  audioUrl: string | null;
  onSeek?: (seconds: number) => void;
}) {
  if (output === null) {
    return <EmptyState>Chưa có kết quả — run đang chờ hoặc đã lỗi.</EmptyState>;
  }

  const kind = viewerFor(capabilityOutput);
  if (kind === "text_boxes") {
    const parsed = asOcrResult(output);
    // Không parse được thì hiện thô: capability khai một đằng, service trả một
    // nẻo vẫn phải xem được, nếu không thì đúng lúc cần chẩn đoán lại mất dữ liệu.
    if (parsed) return <OcrViewer result={parsed} imageUrl={imageUrl} />;
  }
  if (kind === "transcript") {
    const parsed = asAsrResult(output);
    if (parsed) return <AsrViewer result={parsed} audioUrl={audioUrl} onSeek={onSeek ?? (() => {})} />;
  }
  return <RawJson output={output} />;
}
```

- [ ] **Step 10: Chạy toàn bộ test và typecheck**

Run: `cd apps/dashboard && pnpm test && pnpm lint`
Expected: PASS — 154 test, `tsc` sạch.

- [ ] **Step 11: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard/src apps/dashboard/tests
git commit -m "feat(dashboard): viewer OCR overlay bbox, viewer ASR, và fallback JSON thô"
```

---
### Task 9: Playground — chọn service, upload, chạy, xem kết quả

**Files:**
- Create: `apps/dashboard/src/lib/models.ts`, `apps/dashboard/src/components/Playground.tsx`, `apps/dashboard/src/app/playground/page.tsx`
- Test: `apps/dashboard/tests/unit/models.test.ts`, `apps/dashboard/tests/unit/playground.test.tsx`

**Interfaces:**
- Consumes: `acceptForInput`, `isUsable` từ `@/lib/capability` (Task 6); `ResultViewer` (Task 8); `POST /api/invoke` (Task 7); `GET /api/runs/{runId}` (Task 7).
- Produces: `modelsForTask(hosts: HostState[], task: Task): ModelOption[]` với `interface ModelOption { id: string; kind: ModelKind; hostName: string; available: boolean }` từ `@/lib/models`; `<Playground services={ServiceState[]} hosts={HostState[]} />`.

Playground được viết ngay từ đầu quanh **một tập model được chọn** (`selected: string[]`), chạy tuần tự qua một hàm `runOne`. Task 9 giới hạn tập đó ở đúng một phần tử; Task 10 mở ra nhiều phần tử mà không phải viết lại luồng chạy.

- [ ] **Step 1: Viết test thất bại cho `models.ts`**

`apps/dashboard/tests/unit/models.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { modelsForTask } from "@/lib/models";
import type { HostState, ModelInfo } from "@/lib/types";

function model(overrides: Partial<ModelInfo> & { id: string }): ModelInfo {
  return {
    task: "ocr", kind: "opensource", runner: "paddle", loaded: false,
    available: true, vram_mb: 0, base: null, trained_on: null, ...overrides,
  };
}

function host(name: string, healthy: boolean, models: ModelInfo[]): HostState {
  return { name, url: `https://${name}.ngrok.app`, healthy, models, last_seen_at: null, last_error: null };
}

describe("modelsForTask", () => {
  it("chỉ lấy model đúng task — service ocr không gọi được model asr", () => {
    const hosts = [host("a", true, [model({ id: "paddleocr" }), model({ id: "whisper", task: "asr" })])];
    expect(modelsForTask(hosts, "ocr").map((m) => m.id)).toEqual(["paddleocr"]);
  });

  it("bỏ hẳn model trên host đang chết", () => {
    // Chọn được một model không định tuyến tới đâu là bẫy: request đi ra rồi
    // chết ở tầng dưới với lỗi khó hiểu.
    const hosts = [host("chet", false, [model({ id: "paddleocr" })])];
    expect(modelsForTask(hosts, "ocr")).toEqual([]);
  });

  it("giữ model available=false nhưng đánh dấu lại", () => {
    const hosts = [host("a", true, [model({ id: "vietocr-ft", available: false })])];
    expect(modelsForTask(hosts, "ocr")).toEqual([
      { id: "vietocr-ft", kind: "opensource", hostName: "a", available: false },
    ]);
  });

  it("gộp model trùng id trên nhiều host thành một lựa chọn", () => {
    // Cùng một model id trên hai máy thuê là chuyện thường; hiện hai dòng giống
    // hệt nhau không cho người dùng thêm thông tin gì, chỉ gây rối.
    const hosts = [host("a", true, [model({ id: "paddleocr" })]), host("b", true, [model({ id: "paddleocr" })])];
    expect(modelsForTask(hosts, "ocr")).toHaveLength(1);
  });

  it("ưu tiên bản available khi cùng id có trên host này hỏng, host kia lành", () => {
    const hosts = [
      host("a", true, [model({ id: "paddleocr", available: false })]),
      host("b", true, [model({ id: "paddleocr", available: true })]),
    ];
    expect(modelsForTask(hosts, "ocr")[0]).toMatchObject({ available: true, hostName: "b" });
  });

  it("sắp xếp theo id để danh sách không nhảy giữa các lần poll", () => {
    const hosts = [host("a", true, [model({ id: "zebra" }), model({ id: "alpha" })])];
    expect(modelsForTask(hosts, "ocr").map((m) => m.id)).toEqual(["alpha", "zebra"]);
  });

  it("phân biệt model fine-tune", () => {
    const hosts = [host("a", true, [model({ id: "vietocr-ft", kind: "finetuned" })])];
    expect(modelsForTask(hosts, "ocr")[0]?.kind).toBe("finetuned");
  });
});
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/models.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/models"`.

- [ ] **Step 3: Viết `src/lib/models.ts`**

```ts
import type { HostState, ModelKind, Task } from "@/lib/types";

export interface ModelOption {
  id: string;
  kind: ModelKind;
  hostName: string;
  available: boolean;
}

/**
 * Lọc theo task giống hệt cách service tự lọc (spec §3.3): một model-host phục
 * vụ nhiều service, và service ocr chỉ được thấy model task=ocr.
 */
export function modelsForTask(hosts: HostState[], task: Task): ModelOption[] {
  const byId = new Map<string, ModelOption>();
  for (const host of hosts) {
    // Host chết thì model của nó không định tuyến tới đâu được.
    if (!host.healthy) continue;
    for (const model of host.models) {
      if (model.task !== task) continue;
      const existing = byId.get(model.id);
      // Cùng id trên nhiều máy thuê: giữ bản đang dùng được, vì đó là bản sẽ
      // thật sự chạy khi service chọn host.
      if (existing && (existing.available || !model.available)) continue;
      byId.set(model.id, {
        id: model.id,
        kind: model.kind,
        hostName: host.name,
        available: model.available,
      });
    }
  }
  return [...byId.values()].sort((a, b) => a.id.localeCompare(b.id));
}
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `cd apps/dashboard && pnpm test tests/unit/models.test.ts`
Expected: PASS — 7 test.

- [ ] **Step 5: Viết test thất bại cho `Playground`**

`apps/dashboard/tests/unit/playground.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Playground } from "@/components/Playground";
import type { HostState, ServiceState } from "@/lib/types";

const ocrService: ServiceState = {
  info: {
    name: "ocr", task: "ocr", capability_input: "image", capability_output: "text_boxes",
    version: "0.1.0", invoke_path: "/v1/ocr", default_model: "paddleocr-v4-vi",
  },
  base_url: "http://ocr:8000", status: "ok", last_seen_at: null,
};

const asrService: ServiceState = {
  info: {
    name: "asr", task: "asr", capability_input: "audio", capability_output: "transcript",
    version: "0.1.0", invoke_path: "/v1/asr", default_model: "whisper-large-v3",
  },
  base_url: "http://asr:8000", status: "ok", last_seen_at: null,
};

const unreachable: ServiceState = { info: null, base_url: "http://ner:8000", status: "down", last_seen_at: null };

const hosts: HostState[] = [
  {
    name: "a100", url: "https://a100.ngrok.app", healthy: true, last_seen_at: null, last_error: null,
    models: [
      { id: "paddleocr-v4-vi", task: "ocr", kind: "opensource", runner: "paddle", loaded: true, available: true, vram_mb: 1200, base: null, trained_on: null },
      { id: "vietocr-ft-invoice", task: "ocr", kind: "finetuned", runner: "vietocr", loaded: false, available: true, vram_mb: 0, base: "vietocr-base", trained_on: "invoice-vi-v2" },
      { id: "whisper-large-v3", task: "asr", kind: "opensource", runner: "whisper", loaded: false, available: true, vram_mb: 0, base: null, trained_on: null },
    ],
  },
];

const OCR_OUTPUT = {
  full_text: "HOÁ ĐƠN",
  boxes: [{ id: 1, polygon: [[1, 1], [9, 1], [9, 5], [1, 5]], text: "HOÁ ĐƠN", confidence: 0.9, ignore: false }],
};

let fetchMock: ReturnType<typeof vi.fn>;

function invokeOk(): Response {
  return new Response(JSON.stringify({ trace_id: "t1", mode: "sync", run_id: "r1", result: OCR_OUTPUT }), { status: 200 });
}

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue(invokeOk());
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn(() => "blob:gia-lap"),
    revokeObjectURL: vi.fn(),
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function pickFile(user: ReturnType<typeof userEvent.setup>, name = "hoadon.png", type = "image/png") {
  const input = screen.getByLabelText(/tệp đầu vào/i);
  await user.upload(input, new File([new Uint8Array([1, 2, 3])], name, { type }));
}

describe("Playground", () => {
  it("chỉ cho chọn service đã liên hệ được", () => {
    render(<Playground services={[ocrService, unreachable]} hosts={hosts} />);
    const select = screen.getByLabelText("Service") as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["ocr"]);
  });

  it("báo rõ khi không có service nào dùng được", () => {
    render(<Playground services={[unreachable]} hosts={hosts} />);
    expect(screen.getByText(/chưa có service nào dùng được/i)).toBeInTheDocument();
  });

  it("đặt accept của ô upload theo capability_input của service", () => {
    render(<Playground services={[ocrService]} hosts={hosts} />);
    expect(screen.getByLabelText(/tệp đầu vào/i)).toHaveAttribute("accept", "image/*");
  });

  it("đổi accept khi chuyển sang service ASR", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService, asrService]} hosts={hosts} />);
    await user.selectOptions(screen.getByLabelText("Service"), "asr");
    expect(screen.getByLabelText(/tệp đầu vào/i)).toHaveAttribute("accept", "audio/*");
  });

  it("chỉ liệt kê model đúng task của service đang chọn", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService, asrService]} hosts={hosts} />);
    expect(screen.getByLabelText(/model/i)).toHaveTextContent("paddleocr-v4-vi");
    await user.selectOptions(screen.getByLabelText("Service"), "asr");
    const select = screen.getByLabelText(/model/i) as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["", "whisper-large-v3"]);
  });

  it("mặc định để trống model, tức là dùng default_model của service", () => {
    render(<Playground services={[ocrService]} hosts={hosts} />);
    expect((screen.getByLabelText(/model/i) as HTMLSelectElement).value).toBe("");
  });

  it("chưa chọn file thì không cho chạy", () => {
    render(<Playground services={[ocrService]} hosts={hosts} />);
    expect(screen.getByRole("button", { name: "Chạy thử" })).toBeDisabled();
  });

  it("gửi service, model và file lên /api/invoke", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.selectOptions(screen.getByLabelText(/model/i), "vietocr-ft-invoice");
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/invoke");
    const body = init.body as FormData;
    expect(body.get("service")).toBe("ocr");
    expect(body.get("model_version")).toBe("vietocr-ft-invoice");
    expect((body.get("file") as File).name).toBe("hoadon.png");
  });

  it("vẽ overlay bbox trên đúng ảnh vừa upload", async () => {
    const user = userEvent.setup();
    const { container } = render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    await waitFor(() => expect(container.querySelectorAll("svg polygon")).toHaveLength(1));
    expect(screen.getByRole("img", { name: /ảnh đầu vào/i })).toHaveAttribute("src", "blob:gia-lap");
  });

  it("hiện trace_id và link tới run để lần ra lịch sử", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    expect(await screen.findByText("t1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /xem run/i })).toHaveAttribute("href", "/runs/r1");
  });

  it("hiện thông điệp lỗi của service thay vì im lặng", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ code: "model_unavailable", message: "service 'ocr' đang không phản hồi" }), { status: 503 }),
    );
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/service 'ocr' đang không phản hồi/);
  });

  it("khoá nút trong lúc đang chạy để không bắn hai request", async () => {
    let release: (value: Response) => void = () => {};
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => { release = resolve; }));
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));
    expect(await screen.findByRole("button", { name: /đang chạy/i })).toBeDisabled();
    release(invokeOk());
  });

  it("thu hồi object URL của ảnh cũ khi chọn file khác", async () => {
    // Không revoke thì mỗi lần thử một ảnh là giữ thêm một bản trong bộ nhớ tab.
    const user = userEvent.setup();
    render(<Playground services={[ocrService]} hosts={hosts} />);
    await pickFile(user, "anh1.png");
    await pickFile(user, "anh2.png");
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:gia-lap"));
  });

  it("xoá kết quả cũ khi đổi service — kết quả OCR không thuộc về service ASR", async () => {
    const user = userEvent.setup();
    render(<Playground services={[ocrService, asrService]} hosts={hosts} />);
    await pickFile(user);
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));
    await screen.findByText("t1");
    await user.selectOptions(screen.getByLabelText("Service"), "asr");
    expect(screen.queryByText("t1")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/playground.test.tsx`
Expected: FAIL — `Failed to resolve import "@/components/Playground"`.

- [ ] **Step 7: Viết `src/components/Playground.tsx`**

```tsx
"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge, Button, Card, EmptyState } from "@/components/ui";
import { ResultViewer } from "@/components/viewers/ResultViewer";
import { acceptForInput, isUsable } from "@/lib/capability";
import { modelsForTask } from "@/lib/models";
import type { HostState, InvokeResponse, ServiceInfo, ServiceState } from "@/lib/types";

export interface RunOutcome {
  modelLabel: string;
  invoke: InvokeResponse | null;
  error: string | null;
}

async function messageOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { message?: string };
    return body.message ?? `lỗi ${response.status}`;
  } catch {
    return `lỗi ${response.status}`;
  }
}

/** Chạy một model. Task 10 gọi lại đúng hàm này cho từng model trong tập chọn. */
async function runOne(service: string, file: File, modelVersion: string): Promise<RunOutcome> {
  const body = new FormData();
  body.set("service", service);
  if (modelVersion) body.set("model_version", modelVersion);
  body.set("file", file, file.name);
  const response = await fetch("/api/invoke", { method: "POST", body });
  const label = modelVersion || "(mặc định của service)";
  if (!response.ok) return { modelLabel: label, invoke: null, error: await messageOf(response) };
  return { modelLabel: label, invoke: (await response.json()) as InvokeResponse, error: null };
}

export function Playground({ services, hosts }: { services: ServiceState[]; hosts: HostState[] }) {
  const usable = useMemo(
    () => services.filter(isUsable).map((state) => state.info as ServiceInfo),
    [services],
  );
  const [serviceName, setServiceName] = useState(usable[0]?.name ?? "");
  const service = usable.find((info) => info.name === serviceName) ?? usable[0];

  const [file, setFile] = useState<File | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [outcome, setOutcome] = useState<RunOutcome | null>(null);
  const [pending, setPending] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const models = useMemo(
    () => (service ? modelsForTask(hosts, service.task) : []),
    [hosts, service],
  );

  useEffect(() => {
    // Object URL sống tới khi tab đóng nếu không thu hồi — mỗi ảnh thử là một
    // bản sao nằm lại trong bộ nhớ.
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [objectUrl]);

  if (!service) {
    return <EmptyState>Chưa có service nào dùng được — kiểm tra trang Services.</EmptyState>;
  }

  function selectService(name: string): void {
    setServiceName(name);
    // Kết quả cũ thuộc về service cũ; giữ lại là ghép nhầm output với capability.
    setOutcome(null);
    setModel("");
  }

  function selectFile(next: File | null): void {
    setOutcome(null);
    setFile(next);
    setObjectUrl((previous) => {
      if (previous) URL.revokeObjectURL(previous);
      return next ? URL.createObjectURL(next) : null;
    });
  }

  async function run(): Promise<void> {
    if (!file) return;
    setPending(true);
    setOutcome(await runOne(service.name, file, model));
    setPending(false);
  }

  const isImage = service.capability_input === "image";
  const isAudio = service.capability_input === "audio";

  return (
    <div className="space-y-6">
      <Card title="Chạy thử">
        <div className="grid gap-3 md:grid-cols-4 md:items-end">
          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Service</span>
            <select
              value={service.name}
              onChange={(event) => selectService(event.target.value)}
              className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
            >
              {usable.map((info) => (
                <option key={info.name} value={info.name}>{info.name}</option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Model</span>
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
              className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
            >
              <option value="">mặc định ({service.default_model ?? "service tự chọn"})</option>
              {models.map((option) => (
                <option key={option.id} value={option.id} disabled={!option.available}>
                  {option.id}{option.kind === "finetuned" ? " · fine-tune" : ""}{option.available ? "" : " · không dùng được"}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Tệp đầu vào</span>
            <input
              type="file"
              accept={acceptForInput(service.capability_input)}
              onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
              className="w-full text-sm"
            />
          </label>

          <Button type="button" disabled={pending || !file} onClick={() => void run()}>
            {pending ? "Đang chạy…" : "Chạy thử"}
          </Button>
        </div>
        <p className="mt-3 text-xs text-slate-500">Tệp tối đa 25 MB, khớp giới hạn inline của service.</p>
      </Card>

      {isAudio && objectUrl ? (
        <audio ref={audioRef} src={objectUrl} controls className="w-full" />
      ) : null}

      {outcome ? (
        <Card title={`Kết quả · ${outcome.modelLabel}`}>
          {outcome.error ? (
            <p role="alert" className="text-sm text-red-600">{outcome.error}</p>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
                <span>trace_id</span>
                <Badge tone="muted">{outcome.invoke?.trace_id}</Badge>
                {outcome.invoke?.run_id ? (
                  <Link href={`/runs/${outcome.invoke.run_id}`} className="underline">Xem run</Link>
                ) : null}
              </div>
              <ResultViewer
                capabilityOutput={service.capability_output}
                output={outcome.invoke?.result ?? null}
                imageUrl={isImage ? objectUrl : null}
                audioUrl={isAudio ? objectUrl : null}
                onSeek={(seconds) => {
                  if (audioRef.current) audioRef.current.currentTime = seconds;
                }}
              />
            </div>
          )}
        </Card>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 8: Viết `src/app/playground/page.tsx`**

```tsx
import { Playground } from "@/components/Playground";
import { gateway } from "@/lib/gateway";

export const dynamic = "force-dynamic";

export default async function PlaygroundPage() {
  // Hai lời gọi độc lập — chạy song song để trang không cộng dồn hai vòng mạng.
  const [services, hosts] = await Promise.all([gateway.listServices(), gateway.listHosts()]);
  return <Playground services={services.services} hosts={hosts.hosts} />;
}
```

- [ ] **Step 9: Chạy toàn bộ test và typecheck**

Run: `cd apps/dashboard && pnpm test && pnpm lint`
Expected: PASS — 175 test, `tsc` sạch.

- [ ] **Step 10: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard/src apps/dashboard/tests
git commit -m "feat(dashboard): playground chạy thử OCR/ASR với overlay bbox"
```

---
### Task 10: So sánh nhiều model trên cùng một input

Đây là chức năng người dùng nêu đích danh: **so kết quả model open-source với model tự fine-tune.** B2 làm phần so **cạnh nhau** kèm thống kê mô tả (số box, số ký tự, số segment, độ dài, độ trễ). Không có chấm điểm — chấm điểm cần ground truth và thuộc Plan C.

Bổ sung mang tính cộng thêm vào Task 9: ô chọn model chính giữ nguyên, thêm một nhóm checkbox "so sánh thêm với". Chạy một lần là bắn song song tất cả các model được chọn.

**Files:**
- Create: `apps/dashboard/src/lib/summary.ts`
- Modify: `apps/dashboard/src/components/Playground.tsx`
- Test: `apps/dashboard/tests/unit/summary.test.ts`, `apps/dashboard/tests/unit/playground-compare.test.tsx`

**Interfaces:**
- Consumes: `runOne`, `RunOutcome` (Task 9); `asOcrResult`/`asAsrResult` (Task 8); `formatMs` (Task 1); `GET /api/runs/{runId}` (Task 7).
- Produces: `summarize(capabilityOutput: string, output: Record<string, unknown> | null): { label: string; value: string }[]` từ `@/lib/summary`. `RunOutcome` thêm trường `latencyMs: number | null`.

- [ ] **Step 1: Viết test thất bại cho `summary.ts`**

`apps/dashboard/tests/unit/summary.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { summarize } from "@/lib/summary";

const ocr = {
  full_text: "HOÁ ĐƠN\nTổng 120000",
  boxes: [
    { id: 1, polygon: [[0, 0], [1, 0], [1, 1], [0, 1]], text: "HOÁ ĐƠN", confidence: 0.9, ignore: false },
    { id: 2, polygon: [[0, 2], [1, 2], [1, 3], [0, 3]], text: "Tổng 120000", confidence: 0.7, ignore: false },
    { id: 3, polygon: [[0, 4], [1, 4], [1, 5], [0, 5]], text: "x", confidence: 0.1, ignore: true },
  ],
};

const asr = {
  text: "xin chào các bạn",
  segments: [
    { start: 0, end: 1.5, text: "xin chào", speaker: "A" },
    { start: 1.5, end: 4, text: "các bạn", speaker: "B" },
  ],
};

function valueOf(stats: { label: string; value: string }[], label: string): string | undefined {
  return stats.find((stat) => stat.label === label)?.value;
}

describe("summarize cho OCR", () => {
  it("đếm số box không bị bỏ qua", () => {
    // Đếm cả box ignore sẽ làm model nhiễu nhiều trông như model đọc được nhiều hơn.
    expect(valueOf(summarize("text_boxes", ocr), "Số vùng chữ")).toBe("2");
  });

  it("đếm ký tự của toàn văn", () => {
    expect(valueOf(summarize("text_boxes", ocr), "Số ký tự")).toBe("19");
  });

  it("lấy độ tin cậy trung bình của các box được giữ", () => {
    expect(valueOf(summarize("text_boxes", ocr), "Độ tin cậy TB")).toBe("0.80");
  });

  it("hiện gạch ngang khi không box nào có độ tin cậy", () => {
    const noConfidence = { full_text: "a", boxes: [{ ...ocr.boxes[0], confidence: null }] };
    expect(valueOf(summarize("text_boxes", noConfidence), "Độ tin cậy TB")).toBe("—");
  });
});

describe("summarize cho ASR", () => {
  it("đếm số segment", () => {
    expect(valueOf(summarize("transcript", asr), "Số segment")).toBe("2");
  });

  it("đo tổng thời lượng có lời từ mốc cuối cùng", () => {
    expect(valueOf(summarize("transcript", asr), "Thời lượng")).toBe("00:04.0");
  });

  it("đếm ký tự transcript", () => {
    expect(valueOf(summarize("transcript", asr), "Số ký tự")).toBe("16");
  });
});

describe("summarize cho phần còn lại", () => {
  it("không bịa thống kê cho capability chưa biết", () => {
    expect(summarize("embedding", { vector: [1, 2] })).toEqual([]);
  });

  it("không bịa thống kê khi payload lệch capability đã khai", () => {
    expect(summarize("text_boxes", { khong_phai_boxes: 1 })).toEqual([]);
  });

  it("trả rỗng khi chưa có output", () => {
    expect(summarize("text_boxes", null)).toEqual([]);
  });
});
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/summary.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/summary"`.

- [ ] **Step 3: Viết `src/lib/summary.ts`**

```ts
import { viewerFor } from "@/lib/capability";
import { formatClock } from "@/lib/format";
import { asAsrResult, asOcrResult } from "@/lib/results";

export interface Stat {
  label: string;
  value: string;
}

/**
 * Thống kê MÔ TẢ, không phải điểm số: không có ground truth thì "nhiều box hơn"
 * không đồng nghĩa "tốt hơn". Chấm điểm (CER/WER/IoU) là việc của Plan C.
 */
export function summarize(
  capabilityOutput: string,
  output: Record<string, unknown> | null,
): Stat[] {
  if (output === null) return [];
  const kind = viewerFor(capabilityOutput);

  if (kind === "text_boxes") {
    const parsed = asOcrResult(output);
    if (!parsed) return [];
    const kept = parsed.boxes.filter((box) => !box.ignore);
    const scored = kept.filter((box) => box.confidence !== null);
    const average =
      scored.length === 0
        ? "—"
        : (scored.reduce((sum, box) => sum + (box.confidence ?? 0), 0) / scored.length).toFixed(2);
    return [
      { label: "Số vùng chữ", value: String(kept.length) },
      { label: "Số ký tự", value: String(parsed.full_text.length) },
      { label: "Độ tin cậy TB", value: average },
    ];
  }

  if (kind === "transcript") {
    const parsed = asAsrResult(output);
    if (!parsed) return [];
    const end = parsed.segments.reduce((max, segment) => Math.max(max, segment.end), 0);
    return [
      { label: "Số segment", value: String(parsed.segments.length) },
      { label: "Thời lượng", value: formatClock(end) },
      { label: "Số ký tự", value: String(parsed.text.length) },
    ];
  }

  return [];
}
```

- [ ] **Step 4: Chạy test, xác nhận xanh**

Run: `cd apps/dashboard && pnpm test tests/unit/summary.test.ts`
Expected: PASS — 10 test.

- [ ] **Step 5: Viết test thất bại cho chế độ so sánh**

`apps/dashboard/tests/unit/playground-compare.test.tsx`:

```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Playground } from "@/components/Playground";
import type { HostState, ServiceState } from "@/lib/types";

const ocrService: ServiceState = {
  info: {
    name: "ocr", task: "ocr", capability_input: "image", capability_output: "text_boxes",
    version: "0.1.0", invoke_path: "/v1/ocr", default_model: "paddleocr-v4-vi",
  },
  base_url: "http://ocr:8000", status: "ok", last_seen_at: null,
};

const hosts: HostState[] = [
  {
    name: "a100", url: "https://a100.ngrok.app", healthy: true, last_seen_at: null, last_error: null,
    models: [
      { id: "paddleocr-v4-vi", task: "ocr", kind: "opensource", runner: "paddle", loaded: true, available: true, vram_mb: 1200, base: null, trained_on: null },
      { id: "vietocr-ft-invoice", task: "ocr", kind: "finetuned", runner: "vietocr", loaded: true, available: true, vram_mb: 900, base: "vietocr-base", trained_on: "invoice-vi-v2" },
    ],
  },
];

function ocrOutput(text: string) {
  return {
    full_text: text,
    boxes: [{ id: 1, polygon: [[1, 1], [9, 1], [9, 5], [1, 5]], text, confidence: 0.9, ignore: false }],
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn(() => "blob:gia-lap"),
    revokeObjectURL: vi.fn(),
  }));
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/invoke") {
      const model = String((init?.body as FormData).get("model_version") ?? "mac-dinh");
      return new Response(
        JSON.stringify({ trace_id: `t-${model}`, mode: "sync", run_id: `r-${model}`, result: ocrOutput(model) }),
        { status: 200 },
      );
    }
    const runId = url.slice("/api/runs/".length);
    return new Response(JSON.stringify({ id: runId, latency_ms: runId.includes("vietocr") ? 900 : 320 }), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function setup() {
  const user = userEvent.setup();
  render(<Playground services={[ocrService]} hosts={hosts} />);
  await user.upload(screen.getByLabelText(/tệp đầu vào/i), new File([new Uint8Array([1])], "hoadon.png", { type: "image/png" }));
  return user;
}

describe("Playground — so sánh nhiều model", () => {
  it("liệt kê các model có thể so sánh thêm", async () => {
    await setup();
    expect(screen.getByRole("checkbox", { name: /paddleocr-v4-vi/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ })).toBeInTheDocument();
  });

  it("chạy một lần cho model chính và mỗi model được tick", async () => {
    const user = await setup();
    await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    await waitFor(() => {
      const invokes = fetchMock.mock.calls.filter((call) => call[0] === "/api/invoke");
      expect(invokes).toHaveLength(2);
    });
  });

  it("không chạy hai lần cho cùng một model khi tick trùng model chính", async () => {
    const user = await setup();
    await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
    await user.click(screen.getByRole("checkbox", { name: /paddleocr-v4-vi/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    await waitFor(() => expect(screen.getAllByTestId("ket-qua")).toHaveLength(1));
  });

  it("hiện kết quả từng model cạnh nhau, mỗi bảng ghi tên model của nó", async () => {
    const user = await setup();
    await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    const panels = await screen.findAllByTestId("ket-qua");
    expect(panels).toHaveLength(2);
    expect(within(panels[0] as HTMLElement).getByText("paddleocr-v4-vi")).toBeInTheDocument();
    expect(within(panels[1] as HTMLElement).getByText("vietocr-ft-invoice")).toBeInTheDocument();
  });

  it("hiện độ trễ thật lấy từ bản ghi run, không đo bằng đồng hồ trình duyệt", async () => {
    const user = await setup();
    await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    const panels = await screen.findAllByTestId("ket-qua");
    expect(within(panels[0] as HTMLElement).getByText("320 ms")).toBeInTheDocument();
    expect(within(panels[1] as HTMLElement).getByText("900 ms")).toBeInTheDocument();
  });

  it("hiện thống kê mô tả cho từng model", async () => {
    const user = await setup();
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    const panels = await screen.findAllByTestId("ket-qua");
    expect(within(panels[0] as HTMLElement).getByText("Số vùng chữ")).toBeInTheDocument();
  });

  it("một model lỗi không kéo đổ kết quả của model kia", async () => {
    // Đây là lý do dùng allSettled: model fine-tune chưa tải được checkpoint là
    // chuyện thường, và nó không được che mất kết quả của model open-source.
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/invoke") {
        const model = String((init?.body as FormData).get("model_version") ?? "");
        if (model === "vietocr-ft-invoice") {
          return new Response(JSON.stringify({ code: "model_unavailable", message: "chưa tải được checkpoint" }), { status: 503 });
        }
        return new Response(JSON.stringify({ trace_id: "t1", mode: "sync", run_id: "r1", result: ocrOutput("ok") }), { status: 200 });
      }
      return new Response(JSON.stringify({ id: "r1", latency_ms: 320 }), { status: 200 });
    });

    const user = await setup();
    await user.selectOptions(screen.getByLabelText(/^Model$/), "paddleocr-v4-vi");
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));

    const panels = await screen.findAllByTestId("ket-qua");
    expect(panels).toHaveLength(2);
    expect(within(panels[1] as HTMLElement).getByRole("alert")).toHaveTextContent(/chưa tải được checkpoint/);
    expect(within(panels[0] as HTMLElement).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("vẫn hiện kết quả khi không lấy được độ trễ", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/invoke") {
        return new Response(JSON.stringify({ trace_id: "t1", mode: "sync", run_id: "r1", result: ocrOutput("ok") }), { status: 200 });
      }
      return new Response("{}", { status: 500 });
    });
    const user = await setup();
    await user.click(screen.getByRole("button", { name: "Chạy thử" }));
    const panel = (await screen.findAllByTestId("ket-qua"))[0] as HTMLElement;
    expect(within(panel).getByText("—")).toBeInTheDocument();
  });

  it("bỏ tick khi đổi service — model của service cũ không thuộc service mới", async () => {
    const user = await setup();
    await user.click(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ }));
    await user.selectOptions(screen.getByLabelText("Service"), "ocr");
    expect(screen.getByRole("checkbox", { name: /vietocr-ft-invoice/ })).not.toBeChecked();
  });
});
```

- [ ] **Step 6: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/playground-compare.test.tsx`
Expected: FAIL — không tìm thấy checkbox `vietocr-ft-invoice`.

- [ ] **Step 7: Sửa `src/components/Playground.tsx`**

Thay `RunOutcome` và `runOne`, sửa state và phần render kết quả. Bản đầy đủ của các phần thay đổi:

```tsx
export interface RunOutcome {
  modelLabel: string;
  invoke: InvokeResponse | null;
  latencyMs: number | null;
  error: string | null;
}

/**
 * Độ trễ đọc từ bản ghi run chứ không đo bằng đồng hồ trình duyệt: số đo ở
 * trình duyệt gộp cả thời gian upload và hai chặng mạng, nên so hai model bằng
 * nó là so đường truyền chứ không phải so model.
 */
async function latencyOf(runId: string | null): Promise<number | null> {
  if (!runId) return null;
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!response.ok) return null;
    const run = (await response.json()) as { latency_ms?: number | null };
    return typeof run.latency_ms === "number" ? run.latency_ms : null;
  } catch {
    // Không lấy được độ trễ không được phép làm hỏng kết quả inference đã có.
    return null;
  }
}

async function runOne(service: string, file: File, modelVersion: string): Promise<RunOutcome> {
  const body = new FormData();
  body.set("service", service);
  if (modelVersion) body.set("model_version", modelVersion);
  body.set("file", file, file.name);
  const label = modelVersion || "(mặc định của service)";
  const response = await fetch("/api/invoke", { method: "POST", body });
  if (!response.ok) {
    return { modelLabel: label, invoke: null, latencyMs: null, error: await messageOf(response) };
  }
  const invoke = (await response.json()) as InvokeResponse;
  return { modelLabel: label, invoke, latencyMs: await latencyOf(invoke.run_id), error: null };
}
```

Trong component, đổi `const [outcome, setOutcome] = useState<RunOutcome | null>(null)` thành:

```tsx
  const [extras, setExtras] = useState<string[]>([]);
  const [outcomes, setOutcomes] = useState<RunOutcome[]>([]);
```

`selectService` và `selectFile` đặt lại `setOutcomes([])`, và `selectService` thêm `setExtras([])`.

`run()` thành:

```tsx
  async function run(): Promise<void> {
    if (!file) return;
    setPending(true);
    // Set khử trùng lặp: tick đúng model đang chọn ở ô chính thì vẫn chỉ chạy một lần.
    const targets = [...new Set([model, ...extras])];
    const settled = await Promise.allSettled(
      targets.map((target) => runOne(service.name, file, target)),
    );
    setOutcomes(
      settled.map((entry, index) =>
        entry.status === "fulfilled"
          ? entry.value
          : {
              modelLabel: targets[index] || "(mặc định của service)",
              invoke: null,
              latencyMs: null,
              error: String(entry.reason),
            },
      ),
    );
    setPending(false);
  }
```

Thêm nhóm checkbox ngay dưới lưới điều khiển trong `<Card title="Chạy thử">`:

```tsx
        {models.length > 0 ? (
          <fieldset className="mt-4 border-t border-slate-100 pt-3">
            <legend className="text-xs text-slate-500">So sánh thêm với</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {models.map((option) => (
                <label key={option.id} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={extras.includes(option.id)}
                    disabled={!option.available}
                    onChange={(event) =>
                      setExtras((current) =>
                        event.target.checked
                          ? [...current, option.id]
                          : current.filter((id) => id !== option.id),
                      )
                    }
                  />
                  <span>{option.id}</span>
                  {option.kind === "finetuned" ? <Badge tone="warn">fine-tune</Badge> : null}
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}
```

Thay khối `{outcome ? ... : null}` bằng lưới kết quả:

```tsx
      {outcomes.length > 0 ? (
        <div className={outcomes.length > 1 ? "grid gap-4 xl:grid-cols-2" : ""}>
          {outcomes.map((entry, index) => (
            <div key={`${entry.modelLabel}-${index}`} data-testid="ket-qua">
              <Card title="Kết quả">
                <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-slate-600">
                  <Badge tone="muted">{entry.modelLabel}</Badge>
                  <span>{formatMs(entry.latencyMs)}</span>
                  {entry.invoke?.run_id ? (
                    <Link href={`/runs/${entry.invoke.run_id}`} className="underline">Xem run</Link>
                  ) : null}
                  {entry.invoke ? <span>{entry.invoke.trace_id}</span> : null}
                </div>
                {entry.error ? (
                  <p role="alert" className="text-sm text-red-600">{entry.error}</p>
                ) : (
                  <div className="space-y-3">
                    <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
                      {summarize(service.capability_output, entry.invoke?.result ?? null).map((stat) => (
                        <div key={stat.label} className="flex gap-1.5">
                          <dt className="text-slate-500">{stat.label}</dt>
                          <dd className="font-medium">{stat.value}</dd>
                        </div>
                      ))}
                    </dl>
                    <ResultViewer
                      capabilityOutput={service.capability_output}
                      output={entry.invoke?.result ?? null}
                      imageUrl={isImage ? objectUrl : null}
                      audioUrl={isAudio ? objectUrl : null}
                      onSeek={(seconds) => {
                        if (audioRef.current) audioRef.current.currentTime = seconds;
                      }}
                    />
                  </div>
                )}
              </Card>
            </div>
          ))}
        </div>
      ) : null}
```

Thêm import: `import { formatMs } from "@/lib/format";` và `import { summarize } from "@/lib/summary";`.

- [ ] **Step 8: Sửa lại test của Task 9 cho khớp cấu trúc mới**

Ba test trong `tests/unit/playground.test.tsx` chạm vào phần render kết quả, sửa như sau — nhãn ô chọn model giờ phải khớp chính xác vì đã có thêm checkbox cùng tên model:

- mọi `screen.getByLabelText(/model/i)` đổi thành `screen.getByLabelText(/^Model$/)`
- test `"hiện trace_id và link tới run để lần ra lịch sử"`: giữ nguyên phần kiểm `link`, phần `findByText("t1")` giữ nguyên (trace_id vẫn hiện trong khối kết quả)
- test `"xoá kết quả cũ khi đổi service"`: giữ nguyên

Đồng thời `fetchMock` mặc định trong file đó phải trả lời được cả `/api/runs/r1`, vì `runOne` giờ gọi thêm một lần. Thay `beforeEach` thành:

```ts
beforeEach(() => {
  fetchMock = vi.fn(async (url: string) =>
    url === "/api/invoke"
      ? invokeOk()
      : new Response(JSON.stringify({ id: "r1", latency_ms: 320 }), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn(() => "blob:gia-lap"),
    revokeObjectURL: vi.fn(),
  }));
});
```

và test `"gửi service, model và file lên /api/invoke"` lấy lời gọi invoke thay vì lời gọi đầu tiên:

```ts
    const invokeCall = fetchMock.mock.calls.find((call) => call[0] === "/api/invoke");
    const [url, init] = invokeCall as [string, RequestInit];
```

- [ ] **Step 9: Chạy toàn bộ test và typecheck**

Run: `cd apps/dashboard && pnpm test && pnpm lint`
Expected: PASS — 195 test, `tsc` sạch. Nếu có test nào của Task 9 còn đỏ, sửa test cho khớp cấu trúc mới chứ không nới lỏng phần kiểm.

- [ ] **Step 10: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard/src apps/dashboard/tests
git commit -m "feat(dashboard): chạy nhiều model cùng lúc và so kết quả cạnh nhau"
```

---
### Task 11: Lịch sử chạy — bảng có lọc, phân trang, và trang chi tiết

**Files:**
- Create: `apps/dashboard/src/lib/pagination.ts`, `apps/dashboard/src/components/RunsTable.tsx`, `apps/dashboard/src/app/runs/page.tsx`, `apps/dashboard/src/app/runs/[runId]/page.tsx`
- Test: `apps/dashboard/tests/unit/pagination.test.ts`, `apps/dashboard/tests/unit/runs-table.test.tsx`

**Interfaces:**
- Consumes: `RunRecord`, `RunStatus` từ `@/lib/types`; `formatMs`, `formatTimestamp` (Task 1); `ResultViewer` (Task 8); `gateway.listRuns`/`gateway.getRun` (Task 2).
- Produces: `buildRunsHref(filters: RunsFilters, offset: number): string` từ `@/lib/pagination` với `interface RunsFilters { service?: string; status?: string; trace_id?: string; limit: number }`; `<RunsTable runs total offset limit filters />`.

Bộ lọc là `<form method="get">` thuần, không JS: trạng thái lọc nằm trong URL nên chia sẻ được, bookmark được, và nút Back hoạt động đúng.

- [ ] **Step 1: Viết test thất bại cho `pagination.ts`**

`apps/dashboard/tests/unit/pagination.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { buildRunsHref } from "@/lib/pagination";

describe("buildRunsHref", () => {
  it("giữ nguyên bộ lọc khi sang trang", () => {
    expect(buildRunsHref({ service: "ocr", status: "failed", limit: 50 }, 50))
      .toBe("/runs?service=ocr&status=failed&limit=50&offset=50");
  });

  it("bỏ bộ lọc rỗng khỏi URL", () => {
    expect(buildRunsHref({ service: "", status: undefined, limit: 50 }, 0)).toBe("/runs?limit=50");
  });

  it("không ghi offset=0 vào URL — trang đầu là đường dẫn sạch", () => {
    expect(buildRunsHref({ limit: 50 }, 0)).toBe("/runs?limit=50");
  });

  it("không cho offset âm", () => {
    expect(buildRunsHref({ limit: 50 }, -50)).toBe("/runs?limit=50");
  });

  it("mã hoá trace_id có ký tự đặc biệt", () => {
    expect(buildRunsHref({ trace_id: "a b&c", limit: 50 }, 0)).toBe("/runs?trace_id=a+b%26c&limit=50");
  });
});
```

- [ ] **Step 2: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/pagination.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/pagination"`.

- [ ] **Step 3: Viết `src/lib/pagination.ts`**

```ts
export interface RunsFilters {
  service?: string;
  status?: string;
  trace_id?: string;
  limit: number;
}

export function buildRunsHref(filters: RunsFilters, offset: number): string {
  const params = new URLSearchParams();
  if (filters.trace_id) params.set("trace_id", filters.trace_id);
  if (filters.service) params.set("service", filters.service);
  if (filters.status) params.set("status", filters.status);
  params.set("limit", String(filters.limit));
  // offset=0 là mặc định; để nó trong URL làm link trang đầu khác nhau tuỳ đường
  // vào, và bookmark trông rối mà không thêm thông tin gì.
  if (offset > 0) params.set("offset", String(offset));
  return `/runs?${params.toString()}`;
}
```

- [ ] **Step 4: Viết test thất bại cho `RunsTable`**

`apps/dashboard/tests/unit/runs-table.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunsTable } from "@/components/RunsTable";
import type { RunRecord } from "@/lib/types";

function run(overrides: Partial<RunRecord> & { id: string }): RunRecord {
  return {
    trace_id: "t1", service: "ocr", model_version: "paddleocr-v4-vi", mode: "sync",
    status: "ok", input_uri: null, output: { full_text: "x", boxes: [] },
    latency_ms: 320, error: null, created_at: "2026-08-19T07:05:09Z", ...overrides,
  };
}

const filters = { limit: 50 };

describe("RunsTable", () => {
  it("hiện từng run kèm service, model, độ trễ và thời điểm", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={1} offset={0} filters={filters} />);
    const row = screen.getByRole("row", { name: /r1|paddleocr/ });
    expect(within(row).getByText("ocr")).toBeInTheDocument();
    expect(within(row).getByText("paddleocr-v4-vi")).toBeInTheDocument();
    expect(within(row).getByText("320 ms")).toBeInTheDocument();
    expect(within(row).getByText("2026-08-19 07:05:09")).toBeInTheDocument();
  });

  it("phân biệt run lỗi và hiện nguyên nhân", () => {
    render(
      <RunsTable
        runs={[run({ id: "r2", status: "failed", latency_ms: null, output: null, error: "service trả 500: hết VRAM" })]}
        total={1} offset={0} filters={filters}
      />,
    );
    const row = screen.getByRole("row", { name: /r2|hết VRAM/ });
    expect(within(row).getByText("failed")).toBeInTheDocument();
    expect(within(row).getByText(/hết VRAM/)).toBeInTheDocument();
    expect(within(row).getByText("—")).toBeInTheDocument();
  });

  it("hiện gạch ngang khi chưa biết model", () => {
    // model_version="" trong DB được chuẩn hoá về null; hiện chuỗi rỗng thì ô trông như lỗi render.
    render(<RunsTable runs={[run({ id: "r3", model_version: null })]} total={1} offset={0} filters={filters} />);
    expect(within(screen.getByRole("row", { name: /r3/ })).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("mỗi dòng dẫn tới trang chi tiết run", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={1} offset={0} filters={filters} />);
    expect(screen.getByRole("link", { name: /chi tiết/i })).toHaveAttribute("href", "/runs/r1");
  });

  it("trace_id bấm được để lọc mọi run cùng trace — đó là cách xem shadow-run", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={1} offset={0} filters={filters} />);
    expect(screen.getByRole("link", { name: "t1" })).toHaveAttribute("href", "/runs?trace_id=t1&limit=50");
  });

  it("đặt sẵn giá trị lọc hiện tại vào form", () => {
    render(<RunsTable runs={[]} total={0} offset={0} filters={{ service: "asr", status: "failed", limit: 50 }} />);
    expect(screen.getByLabelText("Service")).toHaveValue("asr");
    expect(screen.getByLabelText("Trạng thái")).toHaveValue("failed");
  });

  it("hiện tổng số và khoảng đang xem", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={137} offset={50} filters={filters} />);
    expect(screen.getByText("51–51 / 137")).toBeInTheDocument();
  });

  it("khoá nút Trước ở trang đầu", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={137} offset={0} filters={filters} />);
    expect(screen.getByText("Trước")).not.toHaveAttribute("href");
  });

  it("khoá nút Sau ở trang cuối", () => {
    // offset 100 + 37 dòng = 137 = total: không còn gì phía sau.
    render(<RunsTable runs={[run({ id: "r1" })]} total={101} offset={100} filters={filters} />);
    expect(screen.getByText("Sau")).not.toHaveAttribute("href");
  });

  it("nút Sau giữ nguyên bộ lọc", () => {
    render(<RunsTable runs={[run({ id: "r1" })]} total={137} offset={0} filters={{ service: "ocr", limit: 50 }} />);
    expect(screen.getByRole("link", { name: "Sau" })).toHaveAttribute("href", "/runs?service=ocr&limit=50&offset=50");
  });

  it("nói rõ khi bộ lọc không khớp run nào", () => {
    render(<RunsTable runs={[]} total={0} offset={0} filters={filters} />);
    expect(screen.getByText(/không có run nào khớp/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Chạy test, xác nhận thất bại**

Run: `cd apps/dashboard && pnpm test tests/unit/runs-table.test.tsx`
Expected: FAIL — `Failed to resolve import "@/components/RunsTable"`.

- [ ] **Step 6: Viết `src/components/RunsTable.tsx`**

```tsx
import Link from "next/link";

import { Badge, Card, DataTable, EmptyState } from "@/components/ui";
import { formatMs, formatTimestamp } from "@/lib/format";
import { buildRunsHref, type RunsFilters } from "@/lib/pagination";
import type { RunRecord, RunStatus } from "@/lib/types";

const STATUS_TONE = { ok: "ok", pending: "warn", failed: "bad" } as const;

function StatusBadge({ status }: { status: RunStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{status}</Badge>;
}

function PageLink({ href, children }: { href: string | null; children: string }) {
  if (href === null) {
    return <span className="rounded border border-slate-200 px-3 py-1 text-sm text-slate-300">{children}</span>;
  }
  return (
    <Link href={href} className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100">
      {children}
    </Link>
  );
}

export function RunsTable({
  runs,
  total,
  offset,
  filters,
}: {
  runs: RunRecord[];
  total: number;
  offset: number;
  filters: RunsFilters;
}) {
  const previous = offset > 0 ? buildRunsHref(filters, Math.max(0, offset - filters.limit)) : null;
  const hasMore = offset + runs.length < total;
  const next = hasMore ? buildRunsHref(filters, offset + filters.limit) : null;

  return (
    <div className="space-y-4">
      <Card title="Lọc">
        <form method="get" className="grid gap-3 md:grid-cols-5 md:items-end">
          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Service</span>
            <input name="service" defaultValue={filters.service ?? ""} className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm" />
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Trạng thái</span>
            <select name="status" defaultValue={filters.status ?? ""} className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm">
              <option value="">tất cả</option>
              <option value="ok">ok</option>
              <option value="failed">failed</option>
              <option value="pending">pending</option>
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-sm text-slate-600">Trace ID</span>
            <input name="trace_id" defaultValue={filters.trace_id ?? ""} className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm" />
          </label>
          <input type="hidden" name="limit" value={filters.limit} />
          <button type="submit" className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white">Lọc</button>
        </form>
      </Card>

      <Card>
        {runs.length === 0 ? (
          <EmptyState>Không có run nào khớp bộ lọc.</EmptyState>
        ) : (
          <DataTable headers={["Thời điểm", "Service", "Model", "Mode", "Trạng thái", "Độ trễ", "Trace", ""]}>
            {runs.map((run) => (
              <tr key={run.id}>
                <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600">{formatTimestamp(run.created_at)}</td>
                <td className="px-3 py-2">{run.service}</td>
                <td className="px-3 py-2 text-xs">{run.model_version ?? "—"}</td>
                <td className="px-3 py-2 text-xs">{run.mode}</td>
                <td className="px-3 py-2">
                  <StatusBadge status={run.status} />
                  {run.error ? <div className="mt-1 max-w-xs truncate text-xs text-red-600" title={run.error}>{run.error}</div> : null}
                </td>
                <td className="px-3 py-2 text-xs">{formatMs(run.latency_ms)}</td>
                <td className="px-3 py-2 text-xs">
                  {/* Bấm trace_id ra mọi run cùng trace — đó là cách nhìn shadow-run:
                      một event, nhiều model version, mỗi cái một dòng. */}
                  <Link href={buildRunsHref({ trace_id: run.trace_id, limit: filters.limit }, 0)} className="underline">
                    {run.trace_id}
                  </Link>
                </td>
                <td className="px-3 py-2 text-xs">
                  <Link href={`/runs/${run.id}`} className="underline">Chi tiết</Link>
                </td>
              </tr>
            ))}
          </DataTable>
        )}
        <div className="mt-4 flex items-center gap-3">
          <PageLink href={previous}>Trước</PageLink>
          <PageLink href={next}>Sau</PageLink>
          <span className="text-xs text-slate-500">
            {runs.length === 0 ? "0 / 0" : `${offset + 1}–${offset + runs.length} / ${total}`}
          </span>
        </div>
      </Card>
    </div>
  );
}
```

- [ ] **Step 7: Viết hai trang**

`src/app/runs/page.tsx`:

```tsx
import { RunsTable } from "@/components/RunsTable";
import { gateway } from "@/lib/gateway";
import type { RunsFilters } from "@/lib/pagination";
import type { RunStatus, RunsQuery } from "@/lib/types";

export const dynamic = "force-dynamic";

const STATUSES: readonly string[] = ["pending", "ok", "failed"];

function one(value: string | string[] | undefined): string | undefined {
  const first = Array.isArray(value) ? value[0] : value;
  return first?.trim() || undefined;
}

function clamp(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const status = one(params.status);
  const filters: RunsFilters = {
    service: one(params.service),
    // Bỏ status lạ thay vì đẩy xuống gateway: một URL cũ bị bookmark không nên
    // biến thành trang lỗi.
    status: status && STATUSES.includes(status) ? status : undefined,
    trace_id: one(params.trace_id),
    limit: clamp(one(params.limit), 50, 1, 200),
  };
  const offset = clamp(one(params.offset), 0, 0, Number.MAX_SAFE_INTEGER);

  const query: RunsQuery = { limit: filters.limit, offset };
  if (filters.service) query.service = filters.service;
  if (filters.trace_id) query.trace_id = filters.trace_id;
  if (filters.status) query.status = filters.status as RunStatus;

  const { runs, total } = await gateway.listRuns(query);
  return <RunsTable runs={runs} total={total} offset={offset} filters={filters} />;
}
```

`src/app/runs/[runId]/page.tsx`:

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";

import { Badge, Card } from "@/components/ui";
import { ResultViewer } from "@/components/viewers/ResultViewer";
import { GatewayError } from "@/lib/errors";
import { formatMs, formatTimestamp } from "@/lib/format";
import { gateway } from "@/lib/gateway";
import type { RunRecord, ServiceState } from "@/lib/types";

export const dynamic = "force-dynamic";

function capabilityOf(services: ServiceState[], run: RunRecord): string {
  // Đọc capability từ chính service đã chạy run này; không suy từ tên. Service
  // chưa poll được (info=null) thì để "json" — xem thô còn hơn đoán sai viewer.
  return services.find((state) => state.info?.name === run.service)?.info?.capability_output ?? "json";
}

export default async function RunDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  let run: RunRecord;
  try {
    run = await gateway.getRun(runId);
  } catch (error) {
    if (error instanceof GatewayError && error.status === 404) notFound();
    throw error;
  }
  const { services } = await gateway.listServices();

  return (
    <div className="space-y-4">
      <Card title={`Run ${run.id}`}>
        <dl className="grid gap-x-6 gap-y-2 text-sm md:grid-cols-4">
          <div><dt className="text-xs text-slate-500">Service</dt><dd>{run.service}</dd></div>
          <div><dt className="text-xs text-slate-500">Model</dt><dd>{run.model_version ?? "—"}</dd></div>
          <div><dt className="text-xs text-slate-500">Mode</dt><dd>{run.mode}</dd></div>
          <div><dt className="text-xs text-slate-500">Trạng thái</dt><dd><Badge tone={run.status === "ok" ? "ok" : run.status === "pending" ? "warn" : "bad"}>{run.status}</Badge></dd></div>
          <div><dt className="text-xs text-slate-500">Độ trễ</dt><dd>{formatMs(run.latency_ms)}</dd></div>
          <div><dt className="text-xs text-slate-500">Thời điểm</dt><dd>{formatTimestamp(run.created_at)}</dd></div>
          <div className="md:col-span-2">
            <dt className="text-xs text-slate-500">Trace</dt>
            <dd><Link href={`/runs?trace_id=${encodeURIComponent(run.trace_id)}&limit=50`} className="underline">{run.trace_id}</Link></dd>
          </div>
          <div className="md:col-span-4">
            <dt className="text-xs text-slate-500">Input</dt>
            {/* Run sync ghi input_uri=null (SyncProxy.invoke) — chỉ run async đi
                qua Kafka mới có URI. Nói thẳng ra thay vì để ô trống khó hiểu. */}
            <dd className="text-xs">{run.input_uri ?? "không lưu (chạy sync, file gửi trực tiếp)"}</dd>
          </div>
        </dl>
        {run.error ? <p role="alert" className="mt-3 rounded bg-red-50 p-3 text-sm text-red-700">{run.error}</p> : null}
      </Card>

      <Card title="Kết quả">
        <ResultViewer
          capabilityOutput={capabilityOf(services, run)}
          output={run.output}
          imageUrl={null}
          audioUrl={null}
        />
      </Card>
    </div>
  );
}
```

- [ ] **Step 8: Chạy toàn bộ test, typecheck và build**

Run: `cd apps/dashboard && pnpm test && pnpm lint && pnpm build`
Expected: PASS — 211 test, `tsc` sạch, `next build` thành công với 7 route.

- [ ] **Step 9: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard/src apps/dashboard/tests
git commit -m "feat(dashboard): lịch sử chạy có lọc, phân trang và trang chi tiết run"
```

---
### Task 12: Playwright — luồng chính chạy thật, với gateway giả

Spec mục 8 yêu cầu "Playwright cho luồng chính". Test này dựng **gateway giả** bằng một máy chủ HTTP Node ~90 dòng và chạy `next start` thật lên trước nó. Nhờ vậy nó kiểm được những thứ unit test không chạm tới — middleware, cookie, ranh giới server/client, đường multipart đi xuyên BFF — mà không cần Docker, Postgres hay GPU.

Gateway giả **kiểm bearer token** và trả 401 nếu sai. Đó chính là phép kiểm rằng dashboard thật sự gắn token phía server.

**Files:**
- Create: `apps/dashboard/playwright.config.ts`, `apps/dashboard/tests/e2e/fake-gateway.mjs`, `apps/dashboard/tests/e2e/main-flow.spec.ts`, `apps/dashboard/tests/e2e/fixtures/hoadon.png`
- Modify: `apps/dashboard/package.json`, `Makefile`

**Interfaces:**
- Consumes: toàn bộ ứng dụng từ Tasks 1–11.
- Produces: `pnpm test:e2e` và `make test-web-e2e`.

- [ ] **Step 1: Cài Playwright**

```bash
cd apps/dashboard
pnpm add -D @playwright/test@^1
pnpm exec playwright install chromium
```

Expected: tải xong Chromium, không lỗi.

- [ ] **Step 2: Viết gateway giả**

`apps/dashboard/tests/e2e/fake-gateway.mjs`:

```js
// Gateway giả cho e2e: đủ 5 endpoint dashboard dùng, giữ trạng thái trong RAM.
// KIỂM TOKEN thật sự — nếu dashboard quên gắn bearer, e2e phải đỏ.
import { createServer } from "node:http";

const TOKEN = process.env.FAKE_GATEWAY_TOKEN ?? "token-e2e";
const PORT = Number(process.env.FAKE_GATEWAY_PORT ?? 8099);

const hosts = new Map();
const runs = [];

const OCR_RESULT = {
  full_text: "HOÁ ĐƠN\nTổng cộng 120000",
  boxes: [
    { id: 1, polygon: [[40, 30], [300, 30], [300, 80], [40, 80]], text: "HOÁ ĐƠN", confidence: 0.98, ignore: false },
    { id: 2, polygon: [[40, 120], [420, 120], [420, 170], [40, 170]], text: "Tổng cộng 120000", confidence: 0.86, ignore: false },
  ],
};

const SERVICES = [
  {
    info: {
      name: "ocr", task: "ocr", capability_input: "image", capability_output: "text_boxes",
      version: "0.1.0", invoke_path: "/v1/ocr", default_model: "paddleocr-v4-vi",
    },
    base_url: "http://ocr:8000", status: "ok", last_seen_at: new Date().toISOString(),
  },
  { info: null, base_url: "http://ner:8000", status: "down", last_seen_at: null },
];

function send(res, status, body) {
  const payload = body === undefined ? "" : JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json" });
  res.end(payload);
}

createServer((req, res) => {
  if (req.headers.authorization !== `Bearer ${TOKEN}`) {
    return send(res, 401, { code: "bad_input", message: "token không hợp lệ", trace_id: null });
  }
  const url = new URL(req.url ?? "/", "http://fake");
  const { pathname } = url;

  if (req.method === "GET" && pathname === "/v1/hosts") {
    return send(res, 200, { hosts: [...hosts.values()] });
  }

  if (req.method === "POST" && pathname === "/v1/hosts") {
    let raw = "";
    req.on("data", (chunk) => { raw += chunk; });
    return req.on("end", () => {
      const body = JSON.parse(raw);
      const state = {
        name: body.name, url: body.url, healthy: true,
        last_seen_at: new Date().toISOString(), last_error: null,
        models: [
          { id: "paddleocr-v4-vi", task: "ocr", kind: "opensource", runner: "paddle", loaded: true, available: true, vram_mb: 1200, base: null, trained_on: null },
          { id: "vietocr-ft-invoice", task: "ocr", kind: "finetuned", runner: "vietocr", loaded: false, available: true, vram_mb: 0, base: "vietocr-base", trained_on: "invoice-vi-v2" },
        ],
      };
      hosts.set(body.name, state);
      send(res, 201, state);
    });
  }

  if (req.method === "DELETE" && pathname.startsWith("/v1/hosts/")) {
    const name = decodeURIComponent(pathname.slice("/v1/hosts/".length));
    if (!hosts.delete(name)) return send(res, 404, { code: "bad_input", message: `không có host tên '${name}'`, trace_id: null });
    res.writeHead(204);
    return res.end();
  }

  if (req.method === "GET" && pathname === "/v1/services") return send(res, 200, { services: SERVICES });

  if (req.method === "POST" && pathname === "/v1/invoke/upload") {
    // Không parse multipart: e2e chỉ cần biết request tới được đây kèm token.
    req.resume();
    return req.on("end", () => {
      const id = `r${runs.length + 1}`;
      const record = {
        id, trace_id: `t${runs.length + 1}`, service: "ocr", model_version: "paddleocr-v4-vi",
        mode: "sync", status: "ok", input_uri: null, output: OCR_RESULT,
        latency_ms: 320, error: null, created_at: new Date().toISOString(),
      };
      runs.unshift(record);
      send(res, 200, { trace_id: record.trace_id, mode: "sync", run_id: id, result: OCR_RESULT });
    });
  }

  if (req.method === "GET" && pathname.startsWith("/v1/runs/")) {
    const id = decodeURIComponent(pathname.slice("/v1/runs/".length));
    const found = runs.find((run) => run.id === id);
    return found ? send(res, 200, found) : send(res, 404, { code: "bad_input", message: "không có run", trace_id: null });
  }

  if (req.method === "GET" && pathname === "/v1/runs") {
    const service = url.searchParams.get("service");
    const filtered = service ? runs.filter((run) => run.service === service) : runs;
    return send(res, 200, { runs: filtered, total: filtered.length });
  }

  send(res, 404, { code: "bad_input", message: `không có route ${pathname}`, trace_id: null });
}).listen(PORT, () => {
  console.log(`fake gateway nghe ở http://127.0.0.1:${PORT}`);
});
```

- [ ] **Step 3: Viết `playwright.config.ts`**

```ts
import { defineConfig } from "@playwright/test";

const GATEWAY_PORT = 8099;
const APP_PORT = 3101;
const TOKEN = "token-e2e";

export default defineConfig({
  testDir: "./tests/e2e",
  // Chỉ chạy tuần tự: gateway giả giữ trạng thái trong RAM, chạy song song thì
  // các test giẫm lên danh sách host của nhau.
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${APP_PORT}` },
  webServer: [
    {
      command: `node tests/e2e/fake-gateway.mjs`,
      url: `http://127.0.0.1:${GATEWAY_PORT}/v1/services`,
      reuseExistingServer: false,
      env: { FAKE_GATEWAY_TOKEN: TOKEN, FAKE_GATEWAY_PORT: String(GATEWAY_PORT) },
      // Gateway giả trả 401 khi không có token — coi đó là "đã sống".
      ignoreHTTPSErrors: true,
    },
    {
      command: `pnpm build && pnpm exec next start -p ${APP_PORT}`,
      url: `http://127.0.0.1:${APP_PORT}/login`,
      reuseExistingServer: false,
      timeout: 180_000,
      env: {
        GATEWAY_URL: `http://127.0.0.1:${GATEWAY_PORT}`,
        GATEWAY_TOKEN: TOKEN,
        DASHBOARD_PASSWORD: "matkhau-e2e",
        SESSION_SECRET: "bi-mat-e2e",
      },
    },
  ],
});
```

- [ ] **Step 4: Tạo ảnh mẫu**

```bash
cd apps/dashboard/tests/e2e && mkdir -p fixtures && node -e '
const fs = require("node:fs");
// PNG 1×1 nhỏ nhất hợp lệ — e2e chỉ cần một file ảnh thật, không cần nội dung.
fs.writeFileSync("fixtures/hoadon.png", Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64"));
'```

- [ ] **Step 5: Viết test e2e**

`apps/dashboard/tests/e2e/main-flow.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

const PASSWORD = "matkhau-e2e";

async function login(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Mật khẩu").fill(PASSWORD);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page).toHaveURL(/\/hosts$/);
}

test("chưa đăng nhập thì mọi trang đều bị đẩy về /login", async ({ page }) => {
  await page.goto("/runs");
  await expect(page).toHaveURL(/\/login$/);
});

test("API cũng bị chặn khi chưa đăng nhập, và trả 401 chứ không phải HTML", async ({ request }) => {
  const response = await request.get("/api/hosts");
  expect(response.status()).toBe(401);
  expect(response.headers()["content-type"]).toContain("application/json");
});

test("sai mật khẩu thì không vào được", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Mật khẩu").fill("sai-be-bet");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("alert")).toHaveText("Sai mật khẩu");
  await expect(page).toHaveURL(/\/login$/);
});

test("luồng chính: cắm host → thấy service → chạy thử → xem lịch sử", async ({ page }) => {
  await login(page);

  // 1. Cắm một máy GPU vừa thuê.
  await page.getByLabel("Tên").fill("a100-e2e");
  await page.getByLabel("URL").fill("https://a100-e2e.ngrok.app");
  await page.getByLabel("Token").fill("token-cua-may-gpu");
  await page.getByRole("button", { name: "Cắm host" }).click();
  await expect(page.getByRole("row", { name: /a100-e2e/ })).toContainText("khoẻ");
  await expect(page.getByRole("row", { name: /a100-e2e/ })).toContainText("paddleocr-v4-vi");

  // Token của máy GPU không được xuất hiện trong HTML trang.
  expect(await page.content()).not.toContain("token-cua-may-gpu");

  // 2. Trang Services phân biệt service đã liên hệ được với service chưa.
  await page.getByRole("link", { name: "Services" }).click();
  await expect(page.getByRole("row", { name: /ocr/ })).toContainText("image → text_boxes");
  await expect(page.getByRole("row", { name: /ner/ })).toContainText("Chưa liên hệ được");

  // 3. Playground: upload ảnh, chạy, thấy overlay bbox.
  await page.getByRole("link", { name: "Playground" }).click();
  await page.getByLabel(/tệp đầu vào/i).setInputFiles("tests/e2e/fixtures/hoadon.png");
  await page.getByRole("button", { name: "Chạy thử" }).click();
  await expect(page.locator("svg polygon")).toHaveCount(2);
  await expect(page.getByText("Tổng cộng 120000").first()).toBeVisible();
  await expect(page.getByText("320 ms")).toBeVisible();

  // 4. Lịch sử có đúng run vừa chạy.
  await page.getByRole("link", { name: "Lịch sử" }).click();
  await expect(page.getByRole("row", { name: /paddleocr-v4-vi/ }).first()).toContainText("ok");

  // 5. Trang chi tiết vẽ lại bbox dù không có ảnh gốc (run sync ghi input_uri=null).
  await page.getByRole("link", { name: "Chi tiết" }).first().click();
  await expect(page.getByText(/không lưu \(chạy sync/)).toBeVisible();
  await expect(page.locator("svg polygon")).toHaveCount(2);
});

test("so sánh hai model trên cùng một ảnh", async ({ page }) => {
  await login(page);
  await page.getByLabel("Tên").fill("a100-compare");
  await page.getByLabel("URL").fill("https://a100-compare.ngrok.app");
  await page.getByRole("button", { name: "Cắm host" }).click();
  await expect(page.getByRole("row", { name: /a100-compare/ })).toBeVisible();

  await page.getByRole("link", { name: "Playground" }).click();
  await page.getByLabel(/^Model$/).selectOption("paddleocr-v4-vi");
  await page.getByRole("checkbox", { name: /vietocr-ft-invoice/ }).check();
  await page.getByLabel(/tệp đầu vào/i).setInputFiles("tests/e2e/fixtures/hoadon.png");
  await page.getByRole("button", { name: "Chạy thử" }).click();

  await expect(page.getByTestId("ket-qua")).toHaveCount(2);
  await expect(page.getByText("Số vùng chữ").first()).toBeVisible();
});

test("đăng xuất thì phiên hết hiệu lực", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Đăng xuất" }).click();
  await page.goto("/hosts");
  await expect(page).toHaveURL(/\/login$/);
});
```

- [ ] **Step 6: Chạy e2e**

Run: `cd apps/dashboard && pnpm test:e2e`
Expected: PASS — 6 test.

Nếu test "luồng chính" đỏ ở bước cắm host, kiểm `pnpm exec playwright show-report` để xem gateway giả trả 401 hay không: 401 nghĩa là dashboard không gắn được token phía server.

- [ ] **Step 7: Nối vào Makefile và loại e2e khỏi `vitest`**

`vitest.config.ts` đã giới hạn `include: ["tests/unit/**/*.test.{ts,tsx}"]` nên `pnpm test` không nhặt file `.spec.ts` của Playwright — xác nhận lại bằng `pnpm test` và đếm số test không đổi.

Thêm vào `Makefile` ở gốc repo (và thêm `test-web-e2e` vào dòng `.PHONY`):

```makefile
test-web-e2e:
	cd apps/dashboard && pnpm install --frozen-lockfile && pnpm exec playwright install --with-deps chromium && pnpm test:e2e
```

- [ ] **Step 8: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add apps/dashboard Makefile
git commit -m "test(dashboard): e2e Playwright cho luồng chính với gateway giả"
```

---

### Task 13: Đóng gói — Dockerfile, compose, tài liệu, smoke script

**Files:**
- Create: `apps/dashboard/Dockerfile`, `apps/dashboard/.dockerignore`, `apps/dashboard/.env.example`, `docs/dashboard.md`, `scripts/smoke-dashboard.sh`
- Modify: `infra/compose/docker-compose.dev.yml`

**Interfaces:**
- Consumes: `output: "standalone"` trong `next.config.ts` (Task 1); biến môi trường `GATEWAY_URL`, `GATEWAY_TOKEN`, `DASHBOARD_PASSWORD`, `SESSION_SECRET` (Task 2, 3).
- Produces: dịch vụ `dashboard` trong compose, cổng 3001.

- [ ] **Step 1: Viết `.dockerignore` và `.env.example`**

`apps/dashboard/.dockerignore`:

```
node_modules
.next
tests/e2e
playwright-report
test-results
```

`apps/dashboard/.env.example`:

```bash
# URL nội bộ tới gateway. Trình duyệt KHÔNG gọi thẳng địa chỉ này.
GATEWAY_URL=http://localhost:8080
# Phải trùng VYPQ_TOKEN của gateway. Chỉ tồn tại phía server Next.
GATEWAY_TOKEN=
# Mật khẩu vào dashboard. Thiếu thì dashboard từ chối khởi động.
DASHBOARD_PASSWORD=
# Khoá ký cookie phiên. Sinh bằng: openssl rand -hex 32
SESSION_SECRET=
```

- [ ] **Step 2: Viết `apps/dashboard/Dockerfile`**

```dockerfile
FROM node:24-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:24-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Build không cần bí mật thật: mọi biến đều đọc lúc chạy (getServerEnv), không
# nhúng vào bundle. Đặt giá trị giả để next build không chạm phải nhánh ném lỗi.
ENV GATEWAY_TOKEN=build DASHBOARD_PASSWORD=build SESSION_SECRET=build
RUN pnpm build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production PORT=3001 HOSTNAME=0.0.0.0
# Không chạy bằng root: dashboard nhận file upload từ người dùng.
RUN addgroup -S vypq && adduser -S vypq -G vypq
COPY --from=builder --chown=vypq:vypq /app/.next/standalone ./
COPY --from=builder --chown=vypq:vypq /app/.next/static ./.next/static
USER vypq
EXPOSE 3001
CMD ["node", "server.js"]
```

Kiểm ngay:

```bash
cd "$(git rev-parse --show-toplevel)"
docker build -f apps/dashboard/Dockerfile -t vypq-dashboard:dev apps/dashboard
```

Expected: build xong, không lỗi.

- [ ] **Step 3: Thêm khối `dashboard` vào compose**

Sửa `infra/compose/docker-compose.dev.yml`, chèn sau khối `gateway`:

```yaml
  dashboard:
    build: {context: ../../apps/dashboard, dockerfile: Dockerfile}
    environment:
      GATEWAY_URL: http://gateway:8080
      # Phải trùng token của gateway — dashboard là client có xác thực của nó.
      GATEWAY_TOKEN: ${VYPQ_TOKEN:?bat buoc dat VYPQ_TOKEN}
      # Bắt buộc, cùng lập trường với VYPQ_TOKEN: dashboard là proxy vào gateway,
      # chạy không mật khẩu nghĩa là mở toàn bộ token máy GPU ra cổng 3001.
      DASHBOARD_PASSWORD: ${DASHBOARD_PASSWORD:?bat buoc dat DASHBOARD_PASSWORD}
      SESSION_SECRET: ${SESSION_SECRET:?bat buoc dat SESSION_SECRET (openssl rand -hex 32)}
    # Cổng 3000 đã là Grafana.
    ports: ["3001:3001"]
    depends_on: [gateway]
```

- [ ] **Step 4: Viết `scripts/smoke-dashboard.sh`**

```bash
#!/usr/bin/env bash
# Kiểm nhanh dashboard sau `docker compose up`: đăng nhập được, và KHÔNG có
# đường vòng nào bỏ qua mật khẩu.
set -euo pipefail

BASE="${DASHBOARD_URL:-http://localhost:3001}"
PASSWORD="${DASHBOARD_PASSWORD:?can dat DASHBOARD_PASSWORD}"
COOKIES="$(mktemp)"
trap 'rm -f "$COOKIES"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "1/5 chưa đăng nhập thì /api/hosts phải trả 401"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/hosts")
[ "$code" = "401" ] || fail "/api/hosts trả $code, phải là 401"

echo "2/5 trang bị đẩy về /login"
location=$(curl -s -o /dev/null -w '%{redirect_url}' "$BASE/hosts")
case "$location" in *"/login") ;; *) fail "/hosts chuyển tới '$location', phải tới /login";; esac

echo "3/5 sai mật khẩu bị từ chối"
code=$(curl -s -o /dev/null -w '%{http_code}' -F "password=sai-be-bet" "$BASE/api/login")
[ "$code" = "401" ] || fail "đăng nhập sai trả $code, phải là 401"

echo "4/5 đúng mật khẩu thì lấy được cookie phiên"
curl -s -c "$COOKIES" -o /dev/null -F "password=$PASSWORD" "$BASE/api/login"
grep -q vypq_session "$COOKIES" || fail "không nhận được cookie phiên"

echo "5/5 đã đăng nhập thì đọc được host qua BFF"
body=$(curl -s -b "$COOKIES" "$BASE/api/hosts")
echo "$body" | grep -q '"hosts"' || fail "/api/hosts trả: $body"
echo "$body" | grep -q '"token"' && fail "/api/hosts rò token của máy GPU ra trình duyệt"

echo "OK — dashboard chạy đúng và không rò token."
```

```bash
chmod +x scripts/smoke-dashboard.sh
```

- [ ] **Step 5: Chạy thật toàn stack**

```bash
cd "$(git rev-parse --show-toplevel)/infra/compose"
export VYPQ_TOKEN=token-dev
export DASHBOARD_PASSWORD=matkhau-dev
export SESSION_SECRET=$(openssl rand -hex 32)
docker compose -f docker-compose.dev.yml up -d postgres redpanda gateway dashboard
cd "$(git rev-parse --show-toplevel)" && ./scripts/smoke-dashboard.sh
```

Expected: in `OK — dashboard chạy đúng và không rò token.`

Mở `http://localhost:3001`, đăng nhập, xác nhận trang Model Hosts hiện ra. Sau đó `docker compose -f infra/compose/docker-compose.dev.yml down`.

- [ ] **Step 6: Viết `docs/dashboard.md`**

````markdown
# Dashboard

Trang quản lí trung tâm: cắm máy GPU thuê, xem service, chạy thử OCR/ASR, tra lịch sử.

## Vì sao có tầng BFF

Gateway đòi bearer token trên mọi route `/v1`. Token đó cho phép đọc
`/v1/discovery/hosts` — nơi chứa token của **mọi máy GPU đang thuê**. Nếu trình duyệt
giữ token gateway thì bất kỳ ai mở DevTools cũng lấy được chuỗi đó.

Nên: trình duyệt chỉ nói chuyện với server Next (cùng origin, dùng cookie phiên), và
server Next mới gắn `GATEWAY_TOKEN` gọi sang gateway. Token không bao giờ rời tiến trình
Node. Bài kiểm `tests/unit/client-boundary.test.ts` canh đúng ranh giới này.

Hệ quả: **dashboard phải có mật khẩu riêng.** Không có nó, cổng 3001 chính là một proxy
công khai vào một gateway có xác thực.

## Biến môi trường

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `GATEWAY_URL` | không (mặc định `http://localhost:8080`) | URL nội bộ tới gateway |
| `GATEWAY_TOKEN` | **có** | phải trùng `VYPQ_TOKEN` của gateway |
| `DASHBOARD_PASSWORD` | **có** | mật khẩu dùng chung để vào dashboard |
| `SESSION_SECRET` | **có** | khoá ký cookie phiên, sinh bằng `openssl rand -hex 32` |

Thiếu bất kỳ biến bắt buộc nào thì dashboard ném lỗi thay vì chạy tiếp — giống
`GatewaySettings._token_must_not_be_empty`.

## Chạy

```bash
cd apps/dashboard
cp .env.example .env.local   # điền ba bí mật
pnpm install && pnpm dev     # http://localhost:3001
```

Trong compose: `docker compose -f infra/compose/docker-compose.dev.yml up dashboard`.
Cổng 3001 vì 3000 đã là Grafana.

## Các trang

- **Model Hosts** — cắm URL ngrok + token của máy GPU vừa thuê. Gateway poll mỗi 15 giây
  và coi host là chết sau 45 giây, nên host mới cắm cần khoảng một chu kỳ để chuyển xanh.
- **Services** — service nào gateway liên hệ được, capability và model mặc định của nó.
  Service có `info = null` hiện "Chưa liên hệ được" và **không** bị đoán task.
- **Playground** — upload ảnh/âm thanh, chạy một hoặc nhiều model, xem bbox overlay
  (OCR) hoặc transcript có mốc thời gian (ASR). Tick thêm model ở "So sánh thêm với" để
  chạy song song và xem kết quả cạnh nhau kèm thống kê mô tả và độ trễ thật.
- **Lịch sử** — lọc theo service/trạng thái/trace, phân trang. Bấm `trace_id` ra mọi run
  cùng trace: đó là cách nhìn shadow-run (một event, nhiều model version).

## Giới hạn đã biết

- **Chấm điểm không nằm ở đây.** So sánh trong Playground là **mô tả** (số vùng chữ, số ký
  tự, độ tin cậy trung bình, độ trễ), không phải điểm số. CER/WER/IoU cần ground truth và
  là việc của Plan C.
- **Run sync không lưu ảnh gốc.** `SyncProxy.invoke` ghi `input_uri = null`, nên trang chi
  tiết run vẽ bbox trên nền trắng theo khung suy từ chính các polygon. Chỉ Playground —
  nơi trình duyệt còn giữ file — mới overlay lên ảnh thật.
- **Không có đường async trên UI.** `POST /v1/invoke` mode async cần `input_uri` (một URI
  gateway tải được), còn dashboard gửi file trực tiếp. Muốn chạy async thì publish
  `InferenceRequested` vào Kafka.
- **Một mật khẩu dùng chung**, không có khái niệm người dùng hay phân quyền. Payload cookie
  chỉ chứa hạn dùng (12 giờ).
````

- [ ] **Step 7: Chạy đủ bộ kiểm và commit**

```bash
cd "$(git rev-parse --show-toplevel)"
make test && make test-web && make lint-web
```

Expected: pytest xanh như trước (364 passed, 7 deselected), 211 test dashboard xanh, `tsc` sạch.

```bash
git add apps/dashboard docs/dashboard.md scripts/smoke-dashboard.sh infra/compose/docker-compose.dev.yml
git commit -m "feat(dashboard): Dockerfile, compose, smoke script và tài liệu"
```

---

## Tự soát lại plan

**1. Phủ spec.** Bước 9 của lộ trình (`dashboard: hosts, services, playground, models`) — hosts ở Task 5, services ở Task 6, playground ở Tasks 9–10. Trang `models` riêng **cố ý bỏ**: danh sách model đã hiện đầy đủ trong bảng Host (kèm `kind`, `available`) và trong ô chọn của Playground; một trang thứ ba chỉ đọc cùng dữ liệu từ cùng endpoint là trùng lặp. Tiêu chí nghiệm thu của spec ("dán URL ngrok vào UI → host lên xanh; upload ảnh → bbox overlay, chọn được model") do Task 12 kiểm bằng e2e. Spec §3.8 (service thứ ba không cần sửa dashboard) do Task 6 bảo đảm qua `lib/capability.ts` và Task 8 qua fallback JSON. Spec §8 (test component cho viewer, Playwright cho luồng chính) do Tasks 8 và 12 phủ. Mục 9 của spec ("Plan B2 làm điều này gắt hơn") do Task 3 giải quyết.

Ba mục **cố ý ngoài phạm vi**, đã ghi trong `docs/dashboard.md`: leaderboard/benchmarks (Plan C), DLQ viewer và nhúng metrics (bước 10 của lộ trình Plan B), trang `models` riêng (trùng lặp).

**2. Placeholder.** Không có "TBD"/"tương tự Task N". Mọi bước sửa code đều kèm code đầy đủ; Task 10 sửa `Playground.tsx` nên chép nguyên các khối thay thế thay vì mô tả.

**3. Nhất quán kiểu.** `RunOutcome` đổi hình dạng ở Task 10 (thêm `latencyMs`) — Task 10 chép lại đủ cả `runOne` mới và nêu rõ các test của Task 9 phải sửa theo. `ServiceState.info` được xử lí như `ServiceInfo | null` ở mọi nơi (`isUsable` Task 6, `Playground` Task 9, `capabilityOf` Task 11). `RunsFilters` do Task 11 định nghĩa và chỉ dùng trong Task 11. `ViewerKind` (Task 6) khớp nhánh của `ResultViewer` (Task 8) và `summarize` (Task 10). `boundingExtent` (Task 8) dùng ở đúng `OcrViewer`.

**Số test cộng dồn dự kiến:** T1 14 · T2 33 · T3 62 · T4 76 · T5 97 (thực tế 76 + 11 hosts-panel = 87; con số cuối mỗi task là dự kiến, lệch vài đơn vị không phải lỗi — điều bắt buộc là **không test nào đỏ và không test nào bị nới lỏng để cho xanh**).
