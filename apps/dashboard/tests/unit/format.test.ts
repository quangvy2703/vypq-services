import { describe, expect, it } from "vitest";

import { formatClock, formatMs, formatTimestamp, relativeTime } from "@/lib/format";

describe("formatMs", () => {
  it("hiện mili giây khi dưới một giây", () => {
    expect(formatMs(842)).toBe("842 ms");
  });

  it("đổi sang giây khi từ một giây trở lên", () => {
    expect(formatMs(1500)).toBe("1.50 s");
  });

  it("trả gạch ngang khi chưa có số liệu", () => {
    // run pending và run failed đều có latency_ms = null; hiện "0 ms" ở đó là nói dối.
    expect(formatMs(null)).toBe("—");
  });
});

describe("formatClock", () => {
  it("định dạng mốc thời gian của segment ASR theo mm:ss.s", () => {
    expect(formatClock(0)).toBe("00:00.0");
    expect(formatClock(75.42)).toBe("01:15.4");
  });

  it("giữ được đoạn dài hơn một giờ", () => {
    expect(formatClock(3725.5)).toBe("62:05.5");
  });
});

describe("formatTimestamp", () => {
  it("giữ nguyên phần ngày và giờ theo UTC", () => {
    expect(formatTimestamp("2026-08-19T07:05:09.123456Z")).toBe("2026-08-19 07:05:09");
  });

  it("trả gạch ngang khi null", () => {
    expect(formatTimestamp(null)).toBe("—");
  });

  it("trả nguyên chuỗi khi không phải ngày hợp lệ", () => {
    // Thà hiện thứ gateway thật sự trả về còn hơn hiện "Invalid Date".
    expect(formatTimestamp("khong-phai-ngay")).toBe("khong-phai-ngay");
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-08-19T07:00:00Z");

  it("đếm giây khi vừa mới đây", () => {
    expect(relativeTime("2026-08-19T06:59:50Z", now)).toBe("10 giây trước");
  });

  it("đếm phút", () => {
    expect(relativeTime("2026-08-19T06:52:00Z", now)).toBe("8 phút trước");
  });

  it("đếm giờ", () => {
    expect(relativeTime("2026-08-19T04:00:00Z", now)).toBe("3 giờ trước");
  });

  it("trả 'chưa từng' khi null", () => {
    // host vừa đăng ký chưa poll lần nào: last_seen_at = null.
    expect(relativeTime(null, now)).toBe("chưa từng");
  });

  it("không hiện thời gian âm khi đồng hồ hai máy lệch nhau", () => {
    expect(relativeTime("2026-08-19T07:00:30Z", now)).toBe("vừa xong");
  });
});
