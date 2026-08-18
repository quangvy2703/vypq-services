import io
from dataclasses import dataclass

from PIL import Image, ImageOps
from vypq_contracts.common import ErrorCode
from vypq_core.errors import ServiceError


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    scale: float
    width: int
    height: int


def prepare_image(data: bytes, max_side: int = 2000) -> PreparedImage:
    """Xoay theo EXIF và giới hạn cạnh dài. `scale` để postprocess tính ngược toạ độ."""
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:
        raise ServiceError(ErrorCode.BAD_INPUT, f"không đọc được ảnh: {exc}", 422) from exc

    longest = max(image.size)
    if longest <= max_side:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return PreparedImage(buf.getvalue(), 1.0, image.width, image.height)

    scale = max_side / longest
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)), Image.LANCZOS
    )
    buf = io.BytesIO()
    resized.save(buf, format="PNG")
    return PreparedImage(buf.getvalue(), scale, resized.width, resized.height)
