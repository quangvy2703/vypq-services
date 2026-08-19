import { Nav } from "@/components/Nav";

/**
 * Thanh điều hướng chỉ tồn tại cho các trang đã đăng nhập.
 *
 * Trước đây Nav nằm ở layout gốc nên nó render cả trên /login. Next tự prefetch
 * các Link của nó; những prefetch đó chạy khi chưa có phiên nên bị middleware
 * đẩy về /login, và Router Cache phía client ghi nhớ "/hosts → /login". Sau khi
 * đăng nhập, router.replace("/hosts") đọc trúng bản ghi hỏng đó và quay lại
 * /login mà không phát một request nào — đăng nhập trông như không làm gì cả.
 *
 * Nhóm route này cũng đúng về mặt thiết kế: một trang đăng nhập không nên bày
 * ra các link mà người chưa đăng nhập không đi được.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Nav />
      <main className="mx-auto max-w-6xl space-y-6 p-4">{children}</main>
    </>
  );
}
