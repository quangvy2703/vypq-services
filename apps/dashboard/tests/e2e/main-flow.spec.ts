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

  // 5. Trang chi tiết vẽ lại bbox dù không có ảnh gốc — lần chạy này gửi file
  //    trực tiếp nên không có gì để lưu lại làm nền.
  await page.getByRole("link", { name: "Chi tiết" }).first().click();
  // Không còn nhắc "chạy sync": run sync gửi bằng input_uri VẪN lưu URI đó.
  // Thứ quyết định ô này trống là file gửi trực tiếp, không phải chế độ chạy.
  await expect(page.getByText(/không lưu \(file gửi trực tiếp/)).toBeVisible();
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

test("chạy bằng URL: bbox vẽ lên chính ảnh ở URL đó, cả ở playground lẫn trang run", async ({ page }) => {
  // Nhánh này từng đi thẳng ra sản phẩm với một khung xám: viewer chỉ nhận được
  // objectUrl của tệp, mà chạy bằng URL thì không có tệp nào. jsdom không phân
  // biệt được "ảnh tải được" với "thẻ img rỗng", nên chỗ chứng minh là ở đây.
  await login(page);
  await page.getByLabel("Tên").fill("a100-dan-link");
  await page.getByLabel("URL").fill("https://a100-dan-link.ngrok.app");
  await page.getByRole("button", { name: "Cắm host" }).click();
  await expect(page.getByRole("row", { name: /a100-dan-link/ })).toBeVisible();

  const anhUrl = "http://127.0.0.1:8099/anh-cong-khai.png";
  await page.getByRole("link", { name: "Playground" }).click();
  await page.getByLabel(/URL đầu vào/i).fill(anhUrl);
  await page.getByRole("button", { name: "Chạy thử" }).click();

  const anh = page.getByRole("img", { name: /ảnh đầu vào/i });
  await expect(anh).toHaveAttribute("src", anhUrl);
  // OcrViewer GỠ <img> ra khỏi DOM khi onError, nên còn thấy nó là chưa đủ —
  // naturalWidth > 0 mới chứng minh trình duyệt lấy được bytes thật.
  await expect.poll(() => anh.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator("svg polygon")).toHaveCount(2);

  // Và run đó xem lại được: input_uri đã lưu nên trang chi tiết dựng lại đúng
  // cái nền ảnh, thay vì vẽ bbox trên khung trống như trước.
  await page.getByRole("link", { name: /xem run/i }).click();
  await expect(page.getByRole("link", { name: anhUrl })).toBeVisible();
  await expect(page.getByRole("img", { name: /ảnh đầu vào/i })).toHaveAttribute("src", anhUrl);
});

test("gỡ host đi qua được route có params bất đồng bộ của Next 15", async ({ page }) => {
  // DELETE /api/hosts/{name} là route thứ hai dùng `await context.params`. Unit
  // test tự dựng Promise.resolve({name}) — đúng hình dạng nhưng chưa bao giờ
  // chạy trên router thật. Đây là chỗ duy nhất chứng minh nó hoạt động.
  await login(page);
  await page.getByLabel("Tên").fill("a100-sap-tra-may");
  await page.getByLabel("URL").fill("https://a100-sap-tra-may.ngrok.app");
  await page.getByRole("button", { name: "Cắm host" }).click();
  await expect(page.getByRole("row", { name: /a100-sap-tra-may/ })).toBeVisible();

  // Gỡ host hỏi lại trước — máy thuê hết giờ là chuyện thường, nhưng gỡ nhầm
  // thì mọi service mất một đường định tuyến ngay lập tức.
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: /Gỡ a100-sap-tra-may/i }).click();

  await expect(page.getByRole("row", { name: /a100-sap-tra-may/ })).toHaveCount(0);
});

test("đăng xuất đưa về trang đăng nhập, không phải một trang JSON", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Đăng xuất" }).click();

  // Nav dùng <form method="post"> nên đây là điều hướng thật của trình duyệt.
  // Trả JSON thì người dùng đứng lại ở màn hình {"ok":true} — phiên xoá rồi
  // nhưng không có đường quay lại. Test cũ chỉ goto("/hosts") ngay sau đó nên
  // không bao giờ thấy chỗ nó thật sự dừng chân.
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByLabel("Mật khẩu")).toBeVisible();

  // Và phiên phải thật sự hết hiệu lực, không chỉ là chuyển trang.
  await page.goto("/hosts");
  await expect(page).toHaveURL(/\/login$/);
});
