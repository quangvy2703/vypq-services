const DASH = "—";

export function formatMs(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return DASH;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatClock(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return DASH;
  const parsed = Date.parse(iso);
  // Gateway trả ISO của Postgres; nếu một ngày nào đó nó đổi định dạng, hiện
  // nguyên chuỗi để người vận hành thấy được cái sai, thay vì "Invalid Date".
  if (Number.isNaN(parsed)) return iso;
  return new Date(parsed).toISOString().replace("T", " ").slice(0, 19);
}

export function relativeTime(iso: string | null, nowMs: number): string {
  if (!iso) return "chưa từng";
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return iso;
  const deltaS = Math.floor((nowMs - parsed) / 1000);
  // Máy GPU thuê và máy ứng dụng là hai đồng hồ khác nhau; lệch vài giây là
  // bình thường và "-3 giây trước" trông như lỗi hệ thống.
  if (deltaS < 5) return "vừa xong";
  if (deltaS < 60) return `${deltaS} giây trước`;
  if (deltaS < 3600) return `${Math.floor(deltaS / 60)} phút trước`;
  if (deltaS < 86400) return `${Math.floor(deltaS / 3600)} giờ trước`;
  return `${Math.floor(deltaS / 86400)} ngày trước`;
}
