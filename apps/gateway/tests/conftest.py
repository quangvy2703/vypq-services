import os

# GatewaySettings.token giờ bắt buộc (rỗng thì từ chối khởi động — xem
# GatewaySettings._token_must_not_be_empty). `gateway.main` dựng app ở mức
# module (`app = create_gateway()`) để uvicorn nạp được bằng
# `gateway.main:app`, và nhiều test import thẳng từ `gateway.main`, nên
# `GatewaySettings()` phải chạy được ngay lúc import — kể cả trước khi bất kỳ
# fixture nào kịp chạy. conftest.py được pytest nạp trước mọi test module
# trong thư mục này, nên setdefault ở đây có hiệu lực kịp thời. setdefault để
# không đè token nếu ai đó đã set thật (ví dụ chạy lại smoke test thủ công).
os.environ.setdefault("VYPQ_TOKEN", "test-token")
