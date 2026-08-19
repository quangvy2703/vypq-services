import { render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RelativeTime } from "@/components/RelativeTime";

describe("RelativeTime", () => {
  it("lượt render phía server là mốc tuyệt đối, không phụ thuộc đồng hồ", () => {
    // Đây là phép kiểm chống hydration mismatch: nếu lượt SSR sinh "N giây
    // trước" thì lượt hydrate ở trình duyệt sẽ ra một số khác và React vứt cả
    // cây SSR (React error #418). Đã tái hiện được lỗi đó trên bản build thật.
    const html = renderToString(<RelativeTime iso="2026-08-19T06:59:50Z" />);
    expect(html).toContain("2026-08-19 06:59:50");
    expect(html).not.toMatch(/giây trước|phút trước|giờ trước|vừa xong/);
  });

  it("hai lượt render phía server cách nhau vẫn ra chuỗi giống hệt", () => {
    const iso = "2026-08-19T06:59:50Z";
    expect(renderToString(<RelativeTime iso={iso} />)).toBe(renderToString(<RelativeTime iso={iso} />));
  });

  it("sau khi mount thì đổi sang thời gian tương đối", () => {
    render(<RelativeTime iso={new Date(Date.now() - 8000).toISOString()} />);
    expect(screen.getByText("8 giây trước")).toBeInTheDocument();
  });

  it("host chưa từng được poll hiện 'chưa từng' sau khi mount", () => {
    render(<RelativeTime iso={null} />);
    expect(screen.getByText("chưa từng")).toBeInTheDocument();
  });
});
