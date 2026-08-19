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
