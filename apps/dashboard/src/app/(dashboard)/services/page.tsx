import { PageHeader } from "@/components/ui";
import { ServicesTable } from "@/components/ServicesTable";
import { gateway } from "@/lib/gateway";

// Danh sách service và trạng thái đổi liên tục; không có bản dựng tĩnh nào đúng.
export const dynamic = "force-dynamic";

export default async function ServicesPage() {
  const { services } = await gateway.listServices();
  return (
    <>
      <PageHeader
        title="Services"
        description="Các service tiền/hậu xử lý gateway đang biết, cùng capability chúng tự khai."
      />
      <ServicesTable services={services} />
    </>
  );
}
