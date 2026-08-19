"use client";

import { useEffect, useState } from "react";

import { formatTimestamp, relativeTime } from "@/lib/format";

/**
 * Thời gian tương đối, chỉ tính SAU khi mount.
 *
 * Client component vẫn được render một lượt ở phía server rồi hydrate lại ở
 * trình duyệt, và hai lượt đó có hai `Date.now()` khác nhau. Gọi thẳng
 * `relativeTime(iso, Date.now())` trong thân render vì vậy sinh "8 giây trước"
 * ở lượt SSR và "9 giây trước" ở lượt hydrate — React vứt cả cây SSR rồi render
 * lại từ đầu và log React error #418. Đã tái hiện được trên bản build thật.
 *
 * Nên lượt đầu phải là thứ tất định: mốc tuyệt đối. Chỉ sau khi mount mới đổi
 * sang tương đối, lúc đó chỉ còn một phía đang render nên không thể lệch.
 */
export function RelativeTime({ iso }: { iso: string | null }) {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    setNow(Date.now());
    // Tab quản trị thường mở suốt buổi; không nhịp lại thì "2 phút trước" đứng
    // yên trong khi host đã chết từ lâu.
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  return <span>{now === null ? formatTimestamp(iso) : relativeTime(iso, now)}</span>;
}
