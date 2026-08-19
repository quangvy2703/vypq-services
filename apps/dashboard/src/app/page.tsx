import { redirect } from "next/navigation";

export default function Home() {
  // Trang chủ không có nội dung riêng — thứ người ta mở dashboard để làm đầu
  // tiên là cắm máy GPU vừa thuê vào.
  redirect("/hosts");
}
