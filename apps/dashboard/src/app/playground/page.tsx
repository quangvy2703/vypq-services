import { Playground } from "@/components/Playground";
import { gateway } from "@/lib/gateway";

export const dynamic = "force-dynamic";

export default async function PlaygroundPage() {
  // Hai lời gọi độc lập — chạy song song để trang không cộng dồn hai vòng mạng.
  const [services, hosts] = await Promise.all([gateway.listServices(), gateway.listHosts()]);
  return <Playground services={services.services} hosts={hosts.hosts} />;
}
