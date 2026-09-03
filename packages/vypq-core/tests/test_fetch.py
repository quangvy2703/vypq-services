import asyncio

import httpx
import pytest
import respx
from vypq_core.fetch import DownloadTooLarge, fetch_capped

URI = "http://kho/anh.png"


async def _goi(uri: str = URI, *, max_bytes: int = 1024, deadline_s: float = 5.0):
    async with httpx.AsyncClient() as client:
        return await fetch_capped(client, uri, max_bytes=max_bytes, deadline_s=deadline_s)


@respx.mock
async def test_duoi_han_thi_tra_du_body():
    respx.get(URI).mock(return_value=httpx.Response(200, content=b"x" * 500))
    status, body = await _goi()
    assert status == 200
    assert body == b"x" * 500


@respx.mock
async def test_vuot_han_thi_cat_giua_chung_chu_khong_nap_het():
    # Đây là toàn bộ lý do hàm này tồn tại: `response.content` nạp nguyên body
    # vào RAM, nên một URI trỏ file khổng lồ đủ để hạ tiến trình nhận nó.
    respx.get(URI).mock(return_value=httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(DownloadTooLarge) as exc:
        await _goi(max_bytes=1024)
    assert exc.value.max_bytes == 1024


@respx.mock
async def test_status_loi_thi_khong_doc_body():
    # Body của một trang lỗi không phải input — đọc nó chỉ tổ cho phép một
    # server trả 500 kèm 10GB làm đúng cái việc mà hạn mức này để ngăn.
    respx.get(URI).mock(return_value=httpx.Response(503, content=b"y" * 5000))
    status, body = await _goi(max_bytes=1024)
    assert status == 503
    assert body == b""


@respx.mock
async def test_qua_han_tong_thoi_gian_thi_nem_timeout():
    # timeout của httpx tính theo TỪNG LẦN ĐỌC. Một server nhỏ giọt đều đặn
    # dưới ngưỡng max_bytes không bao giờ chạm timeout đó và giữ connection
    # vô hạn — chỉ deadline tổng mới cắt được.
    async def cham(_request):
        await asyncio.sleep(0.5)
        return httpx.Response(200, content=b"x")

    respx.get(URI).mock(side_effect=cham)
    with pytest.raises(TimeoutError):
        await _goi(deadline_s=0.05)
