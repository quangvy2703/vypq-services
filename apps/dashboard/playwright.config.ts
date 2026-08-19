import { defineConfig } from "@playwright/test";

const GATEWAY_PORT = 8099;
const APP_PORT = 3101;
const TOKEN = "token-e2e";

export default defineConfig({
  testDir: "./tests/e2e",
  // Chạy tuần tự vì gateway giả giữ trạng thái trong RAM và dùng chung cho mọi
  // test. Bộ test hiện tại vẫn xanh khi chạy song song (mỗi test đặt tên host
  // riêng), nên đây là phòng thủ cho test viết sau chứ không phải cách chữa một
  // va chạm đang có.
  workers: 1,
  use: { baseURL: `http://127.0.0.1:${APP_PORT}` },
  webServer: [
    {
      command: `node tests/e2e/fake-gateway.mjs`,
      url: `http://127.0.0.1:${GATEWAY_PORT}/v1/services`,
      reuseExistingServer: false,
      env: { FAKE_GATEWAY_TOKEN: TOKEN, FAKE_GATEWAY_PORT: String(GATEWAY_PORT) },
      // Playwright coi mọi status < 404 là "server đã sống", nên 401 mà gateway
      // giả trả khi thiếu token vẫn tính là sẵn sàng — đúng ý ta muốn.
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
