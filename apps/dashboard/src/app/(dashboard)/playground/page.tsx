import { PageHeader } from "@/components/ui";
import { Playground } from "@/components/Playground";
import { gateway } from "@/lib/gateway";

export const dynamic = "force-dynamic";

export default async function PlaygroundPage() {
  // Hai lời gọi độc lập — chạy song song để trang không cộng dồn hai vòng mạng.
  const [services, hosts] = await Promise.all([gateway.listServices(), gateway.listHosts()]);
  return (
    <>
      <PageHeader
        title="Playground"
        description="Thả một tệp vào hoặc dán URL, chọn model, xem model đọc ra gì. Tick nhiều model để so cạnh nhau."
      />
      <Playground services={services.services} hosts={hosts.hosts} />
    </>
  );
}
