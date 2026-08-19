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
  // getByRole("alert") một mình khớp CẢ role="alert" ẩn mà Next.js tự chèn cho
  // route announcer (#__next-route-announcer__) lẫn <p role="alert"> của form —
  // đây là điều unit test (jsdom, không có runtime Next thật) không thể thấy.
  // Lọc theo nội dung để trỏ đúng phần tử của app.
  await expect(page.locator('[role="alert"]').filter({ hasText: "Sai mật khẩu" })).toHaveText("Sai mật khẩu");
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
  // /^Model$/ không khớp: <label> bao cả <select>, nên tên khả truy cập là nhãn
  // CỘNG giá trị đang chọn ("Model mặc định (paddleocr-v4-vi)"). jsdom tính khác
  // nên unit test dùng /^Model$/ vẫn xanh — đây đúng là loại lệch chỉ trình
  // duyệt thật mới lộ ra.
  await page.getByLabel(/^Model/).selectOption("paddleocr-v4-vi");
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
