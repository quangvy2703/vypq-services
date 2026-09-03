import httpx
import pytest
import respx
from gateway.proxy import SyncProxy
from vypq_core.errors import ServiceError

URI = "http://kho/anh.png"


def _proxy(**kw) -> SyncProxy:
    # fetch() không chạm registry lẫn DB — truyền None để test đúng một việc.
    return SyncProxy(None, None, **kw)


@respx.mock
async def test_tai_url_qua_lon_bi_chan_thay_vi_nap_het_vao_ram():
    # Gateway TỰ tải input_uri rồi mới chuyển tiếp sang service. Không có hạn
    # mức ở đây thì ai gửi được một URL trỏ file lớn là ép gateway giữ ngần ấy
    # RAM — đo được: một URL 60MB đi lọt nguyên vẹn tới tận bước mở ảnh.
    respx.get(URI).mock(return_value=httpx.Response(200, content=b"x" * (3 * 1024 * 1024)))
    with pytest.raises(ServiceError) as exc:
        await _proxy(max_download_mb=1).fetch(URI)
    assert exc.value.http_status == 413
    assert "1MB" in exc.value.message


@respx.mock
async def test_duoi_han_thi_van_tai_binh_thuong():
    respx.get(URI).mock(return_value=httpx.Response(200, content=b"anh"))
    assert await _proxy(max_download_mb=1).fetch(URI) == b"anh"


@respx.mock
async def test_status_loi_van_la_422_nhu_cu():
    respx.get(URI).mock(return_value=httpx.Response(404))
    with pytest.raises(ServiceError) as exc:
        await _proxy().fetch(URI)
    assert exc.value.http_status == 422


async def test_scheme_hong_van_la_422_nhu_cu():
    with pytest.raises(ServiceError) as exc:
        await _proxy().fetch("s3://bucket/a.jpg")
    assert exc.value.http_status == 422
