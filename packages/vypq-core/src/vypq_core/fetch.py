"""Tải input từ URL có chặn cỡ và chặn tổng thời gian.

Ba chỗ trong hệ thống tự tải `input_uri`: gateway (đường sync), worker của mỗi
service (đường Kafka), và model-host (`POST /v1/infer`). Cả ba đều nhận URL do
người ngoài đưa vào, nên cả ba đều cần đúng hai chốt này. Trước đây chỉ
model-host có, mà trong kiến trúc hiện tại model-host lại là chỗ DUY NHẤT không
bao giờ nhận URL — van lắp trên đường không ai đi.

Hàm này CỐ Ý không phân loại lỗi HTTP: mỗi chỗ gọi xếp status thành lỗi khác
nhau và có lý do riêng (worker phải tách 4xx/5xx để chọn giữa DLQ và pause,
gateway thì 422 hết). Gộp lại đây sẽ xoá mất khác biệt đó.
"""

import asyncio

import httpx


class DownloadTooLarge(Exception):
    """Body vượt hạn mức. Chỗ gọi tự chuyển thành lỗi của tầng mình."""

    def __init__(self, uri: str, max_bytes: int) -> None:
        self.uri = uri
        self.max_bytes = max_bytes
        self.max_mb = max_bytes // 1024 // 1024
        super().__init__(f"input vượt quá {self.max_mb}MB")


async def fetch_capped(
    client: httpx.AsyncClient, uri: str, *, max_bytes: int, deadline_s: float
) -> tuple[int, bytes]:
    """Trả `(status_code, body)`. Body rỗng khi status >= 400.

    Đọc theo luồng và cắt ngay khi vượt hạn: `response.content` nạp nguyên body
    vào RAM, nên một URI trỏ file khổng lồ đủ để hạ tiến trình nhận nó.

    Không đọc body của trang lỗi: nó không phải input, và đọc nó cho phép một
    server trả 500 kèm 10GB làm đúng cái việc hạn mức này để ngăn.

    `deadline_s` bọc TOÀN BỘ lời gọi. Timeout của httpx tính theo từng lần đọc,
    nên một server nhỏ giọt đều đặn dưới ngưỡng không bao giờ chạm timeout đó và
    giữ connection vô hạn.
    """
    async with asyncio.timeout(deadline_s):
        async with client.stream("GET", uri) as response:
            if response.status_code >= 400:
                return response.status_code, b""
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise DownloadTooLarge(uri, max_bytes)
                chunks.append(chunk)
            return response.status_code, b"".join(chunks)
