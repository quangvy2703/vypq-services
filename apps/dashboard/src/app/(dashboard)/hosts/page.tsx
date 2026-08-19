import { PageHeader } from "@/components/ui";
import { HostsPanel } from "@/components/HostsPanel";
import { gateway } from "@/lib/gateway";

// Trang này phải phản ánh trạng thái ngay lúc mở; không có bản dựng tĩnh nào đúng.
export const dynamic = "force-dynamic";

export default async function HostsPage() {
  const { hosts } = await gateway.listHosts();
  return (
    <>
      <PageHeader
        title="Model Hosts"
        description="Máy GPU đang thuê. Cắm URL vào đây là mọi service định tuyến được tới model trên đó."
      />
      <HostsPanel hosts={hosts} />
    </>
  );
}
