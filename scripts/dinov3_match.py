#!/usr/bin/env python3
"""Show matching points between 2 images using DINOv3 patch features.

    .venv-dinov3/bin/python scripts/dinov3_match.py [img_a] [img_b] [-o out.png]
"""

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "data/models/dinov3-repo"  # git clone facebookresearch/dinov3
WEIGHTS = ROOT / "data/models/dinov3/dinov3_vit7b16_pretrain_sat493m-a6675841.pth"
IMAGES = ROOT / "data/images"

sys.path.insert(0, str(REPO))
from dinov3.hub import backbones  # noqa: E402

SIZE_MULT = 32  # bội số chung cho ViT (stride 16) và ConvNeXt (stride 32)
IMAGE_SIZE = 768  # chiều CAO sau resize, theo notebook dense_sparse_matching
TOP_K = 40  # số cặp điểm vẽ ra
EXCLUDE = 4  # bán kính (đơn vị patch) loại trừ khi tìm second-best
MIN_STD = 0.03  # std pixel tối thiểu của patch (thang 0..1) để coi là có nội dung

# ImageNet normalization mà DINOv3 dùng
TO_TENSOR = transforms.Compose(
    [
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    ]
)


def build_model(weights: Path):
    """Suy kiến trúc từ tên file weight: dinov3_vitl16_pretrain_*.pth -> dinov3_vitl16."""
    arch = weights.name.split("_pretrain")[0]
    if not hasattr(backbones, arch):
        raise SystemExit(f"khong nhan ra kien truc {arch!r} tu {weights.name}")
    # truyền weights để builder tự bật cờ kiến trúc suy từ hash trong tên file
    # (vd. bản sat493m cần untie_global_and_local_cls_norm); pretrained=False
    # để nó khỏi copy checkpoint vào cache của torch.hub — ta tự nạp bên dưới.
    model = getattr(backbones, arch)(pretrained=False, weights=str(weights))
    model.load_state_dict(torch.load(weights, map_location="cpu"))
    return model.eval(), arch


def load_image(path: Path, gray: bool) -> Image.Image:
    """Đọc ảnh, (tuỳ chọn) chuyển xám, resize giữ tỉ lệ, hai cạnh bội số SIZE_MULT."""
    img = Image.open(path)
    # ảnh PNG/WebP có alpha: dán lên nền trắng trước, tránh viền đen giả
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    img = img.convert("L").convert("RGB") if gray else img.convert("RGB")

    # theo notebook: đặt CHIỀU CAO = IMAGE_SIZE, bề rộng scale theo tỉ lệ,
    # cả hai cắt xuống bội số của SIZE_MULT.
    w, h = img.size
    h_units = IMAGE_SIZE // SIZE_MULT
    w_units = max(1, int(w * IMAGE_SIZE / (h * SIZE_MULT)))
    return img.resize((w_units * SIZE_MULT, h_units * SIZE_MULT), Image.BILINEAR)


def content_mask(img: Image.Image, min_std: float, stride: int) -> torch.Tensor:
    """True cho patch có nội dung. Patch trơn (nền trắng, trời) có std ~ 0 -> loại.

    Không lọc thì chúng vẫn được match: patch trắng nào cũng giống patch trắng nào,
    và RoPE khiến hai patch trắng cùng vị trí trông rất "khớp".
    """
    g = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
    gh, gw = img.height // stride, img.width // stride
    tiles = g.reshape(gh, stride, gw, stride).swapaxes(1, 2).reshape(-1, stride * stride)
    return torch.from_numpy(tiles.std(axis=1) > min_std)


@torch.inference_mode()
def patch_features(model, img: Image.Image, device="cpu"):
    """Trả về (feat, grid_w, stride). feat đã chuẩn hoá L2, shape (N, D).

    Stride suy từ số token thay vì hard-code: ViT/16 ra 16, ConvNeXt ra 32.
    """
    x = TO_TENSOR(img)[None].to(device)
    feat = model.forward_features(x)["x_norm_patchtokens"][0].float().cpu()
    stride = round((img.width * img.height / feat.shape[0]) ** 0.5)
    return F.normalize(feat, dim=-1), img.width // stride, stride


def patch_center(idx: int, grid_w: int, stride: int):
    """Chỉ số patch -> toạ độ pixel tâm patch."""
    row, col = idx // grid_w, idx % grid_w
    return (col + 0.5) * stride, (row + 0.5) * stride


def match(fa, fb, mask_a, mask_b, grid_w_b: int, top_k: int):
    """Mutual nearest-neighbour, xếp hạng theo độ độc nhất (Lowe ratio)."""
    sim = fa @ fb.T  # (Na, Nb) — cosine similarity
    sim[:, ~mask_b] = -1.0  # không cho match vào patch trơn của ảnh B

    ia = torch.arange(fa.shape[0])
    best = sim.argmax(dim=1)
    keep = mask_a & (sim.argmax(dim=0)[best] == ia)  # hai bên cùng chọn nhau

    # second-best, bỏ vùng lân cận của best (patch kề nhau luôn giống nhau)
    idx_b = torch.arange(fb.shape[0])
    dy = (idx_b // grid_w_b)[None, :] - (best // grid_w_b)[:, None]
    dx = (idx_b % grid_w_b)[None, :] - (best % grid_w_b)[:, None]
    near = (dy.abs() <= EXCLUDE) & (dx.abs() <= EXCLUDE)
    second = sim.masked_fill(near, -1.0).max(dim=1).values

    # ratio thấp = patch nổi trội hẳn so với phần còn lại của ảnh B.
    # Feature DINOv3 rất mượt nên ratio luôn sát 1 -> xếp hạng, không cắt ngưỡng.
    ratio = second / sim[ia, best].clamp(min=1e-6)
    ia, ib = ia[keep], best[keep]
    order = ratio[keep].argsort()[:top_k]
    ia, ib = ia[order], ib[order]
    return ia, ib, sim[ia, ib]


def draw(img_a, img_b, ia, ib, scores, ga, gb, sa, sb, out_path: Path, title=""):
    wa, ha = img_a.size
    wb, hb = img_b.size
    canvas = np.full((max(ha, hb), wa + wb, 3), 255, dtype=np.uint8)
    canvas[:ha, :wa] = np.asarray(img_a)
    canvas[:hb, wa:] = np.asarray(img_b)

    fig, ax = plt.subplots(figsize=((wa + wb) / 100, max(ha, hb) / 100), dpi=150)
    ax.imshow(canvas)
    ax.axis("off")

    cmap = plt.get_cmap("turbo")
    lo, hi = float(scores.min()), float(scores.max())
    for a, b, s in zip(ia.tolist(), ib.tolist(), scores.tolist()):
        xa, ya = patch_center(a, ga, sa)
        xb, yb = patch_center(b, gb, sb)
        color = cmap((s - lo) / (hi - lo + 1e-8))
        ax.plot([xa, xb + wa], [ya, yb], "-", color=color, lw=0.9, alpha=0.85)
        ax.plot([xa, xb + wa], [ya, yb], ".", color=color, ms=4)

    ax.set_title(f"{title} — {len(ia)} matches", fontsize=8)
    fig.tight_layout(pad=0.2)
    fig.savefig(out_path, bbox_inches="tight")
    print(f"saved -> {out_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("image_a", nargs="?", default=str(IMAGES / "logo1.webp"))
    p.add_argument("image_b", nargs="?", default=str(IMAGES / "logo2.png"))
    p.add_argument("-o", "--out", default=str(IMAGES / "matches.png"))
    p.add_argument("-k", "--top-k", type=int, default=TOP_K)
    p.add_argument("-w", "--weights", default=str(WEIGHTS))
    p.add_argument(
        "--gray",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="chuyển xám trước khi trích feature (--no-gray để giữ màu)",
    )
    p.add_argument(
        "--min-std",
        type=float,
        default=MIN_STD,
        help="ngưỡng loại patch trơn; 0 = tắt lọc",
    )
    p.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    args = p.parse_args()

    weights = Path(args.weights)
    print(f"loading {weights.name} ...")
    model, arch = build_model(weights)
    model.to(args.device)

    img_a = load_image(Path(args.image_a), args.gray)
    img_b = load_image(Path(args.image_b), args.gray)
    fa, ga, sa = patch_features(model, img_a, args.device)
    fb, gb, sb = patch_features(model, img_b, args.device)

    mask_a = content_mask(img_a, args.min_std, sa)
    mask_b = content_mask(img_b, args.min_std, sb)
    print(f"patches: {int(mask_a.sum())}/{len(mask_a)} vs {int(mask_b.sum())}/{len(mask_b)}")

    ia, ib, scores = match(fa, fb, mask_a, mask_b, gb, args.top_k)
    if len(ia) == 0:
        print("no match")
        return
    print(f"matches: {len(ia)}  (cosine {scores.min():.3f} .. {scores.max():.3f})")
    draw(img_a, img_b, ia, ib, scores, ga, gb, sa, sb, Path(args.out), arch)


if __name__ == "__main__":
    main()
