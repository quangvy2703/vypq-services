import { HostsPanel } from "@/components/HostsPanel";
import { gateway } from "@/lib/gateway";

// Trang này phải phản ánh trạng thái ngay lúc mở; không có bản dựng tĩnh nào đúng.
export const dynamic = "force-dynamic";

export default async function HostsPage() {
  const { hosts } = await gateway.listHosts();
  return <HostsPanel hosts={hosts} />;
}
