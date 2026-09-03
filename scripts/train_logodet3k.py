#!/usr/bin/env python3
"""Train YOLO (ultralytics) trên LogoDet-3K — export parquet ra YOLO rồi train, trong 1 file.

    uv run --no-project --with ultralytics --with pyarrow --with pillow \
        scripts/train_logodet3k.py --classes brand --epochs 100 --batch 16

Dataset gốc là parquet của HuggingFace: mỗi dòng = 1 ảnh (bytes JPEG) + 1 box
[x1, y1, x2, y2] tuyệt đối + company_name (ClassLabel 3000 brand) + industry_name.
Bước export ghi ra layout YOLO chuẩn (images/labels × train/val) và được cache lại,
lần chạy sau chỉ train nếu cấu hình export không đổi.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/dataset/logodet-3k"  # nơi chứa *.parquet tải từ HF
OUT_ROOT = ROOT / "data/dataset/logodet-3k-yolo"  # dataset YOLO sinh ra
RUNS_DIR = ROOT / "data/runs"

# Ảnh giữ nguyên bytes gốc nếu format nằm trong đây, còn lại re-encode sang JPEG.
PASSTHROUGH = {"JPEG": ".jpg", "PNG": ".png", "BMP": ".bmp", "WEBP": ".webp"}
EXIF_ORIENTATION = 274  # tag orientation; khác 1 là phải re-encode để bỏ xoay ngầm
BATCH_ROWS = 32  # số dòng đọc mỗi lần từ parquet, giữ RAM thấp vì mỗi dòng ~40KB ảnh

# Default augmentation của ultralytics 8.4 (chép ra để log được và để pin, khỏi trôi
# theo bản mới). Mọi giá trị đều override được bằng cờ dòng lệnh cùng tên.
ULTRALYTICS_AUG = {
    "hsv_h": 0.015,  # xoay hue
    "hsv_s": 0.7,  # đổi bão hoà
    "hsv_v": 0.4,  # đổi độ sáng
    "degrees": 0.0,  # xoay ảnh (độ)
    "translate": 0.1,  # tịnh tiến
    "scale": 0.5,  # phóng/thu
    "shear": 0.0,  # nghiêng
    "perspective": 0.0,  # biến đổi phối cảnh
    "flipud": 0.0,  # lật dọc
    "fliplr": 0.5,  # lật ngang
    "bgr": 0.0,  # đảo kênh RGB<->BGR
    "mosaic": 1.0,  # ghép 4 ảnh
    "close_mosaic": 10,  # tắt mosaic ở N epoch cuối
    "mixup": 0.0,
    "cutmix": 0.0,
    "copy_paste": 0.0,  # chỉ có tác dụng khi dataset có mask segment
}

# Preset mặc định, chỉnh cho ảnh logo đời thường: logo nằm trên biển hiệu / bao bì
# nên hay bị nghiêng và nhìn chéo, ba phép hình học dưới đây mô phỏng đúng chuyện đó.
# Giữ mixup/cutmix = 0: trộn 2 ảnh sinh nhãn lai, rất hại khi phải phân biệt 3000
# brand gần giống nhau — chỉ bật khi thấy overfit rõ (train tốt, val tệ).
LOGO_AUG = ULTRALYTICS_AUG | {
    "degrees": 5.0,
    "shear": 2.0,
    "perspective": 0.0005,
}

# Hai phép biến đổi phá nhãn khi phải phân biệt brand: lật ngang biến chữ trong logo
# thành ảnh gương, còn xoay hue phá màu thương hiệu (Coca-Cola đỏ vs Pepsi xanh).
# Chế độ --classes logo không phân biệt brand nên không cần chặn.
BRAND_SAFE_AUG = {"fliplr": 0.0, "hsv_h": 0.0}

AUG_PRESETS = {
    "logo": LOGO_AUG,
    "ultralytics": ULTRALYTICS_AUG,  # đúng y default thư viện, kể cả lật ngang
    "none": dict.fromkeys(ULTRALYTICS_AUG, 0.0) | {"close_mosaic": 0},  # baseline
}


# --------------------------------------------------------------------------- data


def shard_files(split: str) -> list[Path]:
    """Các file parquet của một split, sắp xếp ổn định để index shard không đổi."""
    return sorted(DATA_DIR.glob(f"{split}-*.parquet"))


def brand_names() -> list[str]:
    """3000 tên brand lấy từ metadata HF nhúng trong schema parquet."""
    import pyarrow.parquet as pq

    files = shard_files("train") or shard_files("test")
    meta = pq.ParquetFile(files[0]).schema_arrow.metadata[b"huggingface"]
    features = json.loads(meta.decode())["info"]["features"]
    return list(features["company_name"]["names"])


def industry_names() -> list[str]:
    """industry_name là string tự do nên phải quét cột để lấy tập nhãn."""
    import pyarrow.parquet as pq

    seen: set[str] = set()
    for split in ("train", "test"):
        for path in shard_files(split):
            table = pq.read_table(path, columns=["industry_name"])
            seen.update(table.column("industry_name").to_pylist())
    return sorted(seen)


def class_names(mode: str) -> list[str]:
    if mode == "brand":
        return brand_names()
    if mode == "industry":
        return industry_names()
    return ["logo"]


# ------------------------------------------------------------------------- export


def _encode(raw: bytes) -> tuple[bytes, str, int, int] | None:
    """Trả (bytes ghi ra đĩa, đuôi file, W, H). None nếu ảnh hỏng.

    Ảnh có EXIF orientation != 1 được re-encode bỏ EXIF: PIL đọc kích thước theo
    pixel thật còn ultralytics lại dùng exif_size(), lệch nhau thì box sai.
    """
    from PIL import Image

    try:
        im = Image.open(BytesIO(raw))
        width, height = im.size
        fmt = im.format or ""
        rotated = im.getexif().get(EXIF_ORIENTATION, 1) not in (1, None)
    except Exception:
        return None
    if width < 2 or height < 2:
        return None

    if fmt in PASSTHROUGH and not rotated:
        return raw, PASSTHROUGH[fmt], width, height

    buf = BytesIO()
    try:
        im.convert("RGB").save(buf, format="JPEG", quality=95)  # bỏ EXIF, bỏ mọi format lạ
    except Exception:
        return None
    return buf.getvalue(), ".jpg", width, height


def _yolo_line(cls: int, box: list[int], width: int, height: int) -> str | None:
    """[x1,y1,x2,y2] tuyệt đối -> 'cls cx cy w h' chuẩn hoá. None nếu box suy biến."""
    x1, y1, x2, y2 = box
    x1, x2 = sorted((max(0, min(x1, width)), max(0, min(x2, width))))
    y1, y2 = sorted((max(0, min(y1, height)), max(0, min(y2, height))))
    bw, bh = x2 - x1, y2 - y1
    if bw < 1 or bh < 1:
        return None
    cx, cy = (x1 + x2) / 2 / width, (y1 + y2) / 2 / height
    return f"{cls} {cx:.6f} {cy:.6f} {bw / width:.6f} {bh / height:.6f}\n"


def export_shard(job: dict) -> dict:
    """Đổ 1 file parquet ra images/labels. Chạy trong process riêng nên phải top-level."""
    import pyarrow.parquet as pq

    split, shard_idx = job["split"], job["shard_idx"]
    mode, limit = job["mode"], job["limit"]
    industry_ids: dict[str, int] = job["industry_ids"]
    img_dir = Path(job["img_dir"])
    lbl_dir = Path(job["lbl_dir"])

    parquet = pq.ParquetFile(job["path"])
    written = skipped_image = skipped_box = 0
    row_idx = -1
    for batch in parquet.iter_batches(batch_size=BATCH_ROWS):
        for row in batch.to_pylist():
            row_idx += 1
            if limit and written >= limit:
                return _export_result(job, written, skipped_image, skipped_box)

            encoded = _encode(row["image_path"]["bytes"])
            if encoded is None:
                skipped_image += 1
                continue
            blob, ext, width, height = encoded

            if mode == "brand":
                cls = int(row["company_name"])
            elif mode == "industry":
                cls = industry_ids[row["industry_name"]]
            else:
                cls = 0
            line = _yolo_line(cls, list(row["bbox"]), width, height)
            if line is None:
                skipped_box += 1  # ảnh vẫn giữ, label rỗng = background cho YOLO
                line = ""

            stem = f"{split}_{shard_idx:02d}_{row_idx:06d}"
            (img_dir / f"{stem}{ext}").write_bytes(blob)
            (lbl_dir / f"{stem}.txt").write_text(line)
            written += 1
    return _export_result(job, written, skipped_image, skipped_box)


def _export_result(job: dict, written: int, skipped_image: int, skipped_box: int) -> dict:
    return {
        "name": Path(job["path"]).name,
        "split": job["split"],
        "written": written,
        "skipped_image": skipped_image,
        "skipped_box": skipped_box,
    }


def export_fingerprint(mode: str, limit: int, val_from: str) -> str:
    """Dấu vân tay của lần export: nguồn + cấu hình. Khớp thì bỏ qua export."""
    parts = [mode, str(limit), val_from]
    for split in ("train", "test"):
        for path in shard_files(split):
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def write_data_yaml(out_root: Path, names: list[str]) -> Path:
    """Tự viết YAML (json.dumps để escape) — khỏi phụ thuộc PyYAML khi chỉ export."""
    lines = [
        f"path: {out_root}",
        "train: images/train",
        "val: images/val",
        "names:",
        *[f"  {i}: {json.dumps(name)}" for i, name in enumerate(names)],
    ]
    yaml_path = out_root / "data.yaml"
    yaml_path.write_text("\n".join(lines) + "\n")
    return yaml_path


def export_dataset(args) -> tuple[Path, list[str]]:
    """Parquet -> layout YOLO. Trả (đường dẫn data.yaml, danh sách tên lớp)."""
    out_root = Path(args.out).resolve()
    manifest = out_root / "export.json"
    fingerprint = export_fingerprint(args.classes, args.limit, args.val_from)

    if manifest.exists() and not args.force_export:
        cached = json.loads(manifest.read_text())
        if cached.get("fingerprint") == fingerprint:
            print(f"[export] dùng lại dataset đã có: {out_root} ({cached['counts']})")
            return out_root / "data.yaml", cached["names"]

    names = class_names(args.classes)
    industry_ids = {name: i for i, name in enumerate(names)} if args.classes == "industry" else {}

    print(f"[export] {len(names)} lớp ({args.classes}) -> {out_root}")
    for sub in ("images", "labels"):
        shutil.rmtree(out_root / sub, ignore_errors=True)  # tránh sót file của lần export cũ
    for split in ("train", "val"):
        (out_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    jobs = []
    for src_split, dst_split in (("train", "train"), (args.val_from, "val")):
        for shard_idx, path in enumerate(shard_files(src_split)):
            jobs.append(
                {
                    "path": str(path),
                    "split": dst_split,
                    "shard_idx": shard_idx,
                    "mode": args.classes,
                    "limit": args.limit,
                    "industry_ids": industry_ids,
                    "img_dir": str(out_root / "images" / dst_split),
                    "lbl_dir": str(out_root / "labels" / dst_split),
                }
            )

    counts = {"train": 0, "val": 0}
    skipped_image = skipped_box = 0
    with ProcessPoolExecutor(max_workers=args.export_workers) as pool:
        futures = [pool.submit(export_shard, job) for job in jobs]
        for done, future in enumerate(as_completed(futures), 1):
            res = future.result()
            counts[res["split"]] += res["written"]
            skipped_image += res["skipped_image"]
            skipped_box += res["skipped_box"]
            print(
                f"[export] {done}/{len(futures)} {res['name']} -> {res['split']}: "
                f"{res['written']} ảnh (lỗi decode {res['skipped_image']}, "
                f"box suy biến {res['skipped_box']})"
            )

    if not counts["train"]:
        sys.exit(f"[export] không ghi được ảnh train nào từ {DATA_DIR}")
    print(f"[export] xong: {counts} — bỏ {skipped_image} ảnh hỏng, {skipped_box} box suy biến")

    yaml_path = write_data_yaml(out_root, names)
    manifest.write_text(json.dumps({"fingerprint": fingerprint, "counts": counts, "names": names}))
    return yaml_path, names


# -------------------------------------------------------------------------- train


def pick_device(requested: str) -> str:
    """auto = dùng HẾT GPU đang thấy. Nhiều GPU thì ultralytics tự chuyển sang DDP.

    Trả về đúng chuỗi ultralytics chờ đợi: "0,1" cho 2 GPU, "mps", hay "cpu".
    Muốn ghim 1 card thì truyền thẳng --device 0 (hoặc set CUDA_VISIBLE_DEVICES).
    """
    import torch

    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return ",".join(str(i) for i in range(torch.cuda.device_count()))
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def augmentation_config(args) -> dict:
    """Preset + chặn phép biến đổi phá nhãn brand + override từ dòng lệnh."""
    cfg = dict(AUG_PRESETS[args.aug_preset])
    if args.aug_preset == "logo" and args.classes in ("brand", "industry"):
        cfg |= BRAND_SAFE_AUG
    for key in cfg:
        override = getattr(args, key, None)
        if override is not None:
            cfg[key] = override
    return cfg


def train(args, yaml_path: Path, names: list[str]) -> None:
    from ultralytics import YOLO

    device = pick_device(args.device)
    gpus = device.split(",") if device not in ("cpu", "mps") else []
    print(f"[train] model={args.model} device={device} classes={len(names)}")
    if len(gpus) > 1:
        # ultralytics coi --batch là TỔNG, rồi chia cho số GPU (batch // world_size).
        # Không chia hết thì phần dư bị bỏ, mỗi rank chạy batch nhỏ hơn mong đợi.
        print(
            f"[train] DDP {len(gpus)} GPU — batch {args.batch} tổng = {args.batch // len(gpus)}/GPU"
        )
        if args.batch % len(gpus):
            print(f"[train] CẢNH BÁO: --batch {args.batch} không chia hết cho {len(gpus)} GPU")
        if args.batch < 1:
            sys.exit(f"AutoBatch (--batch {args.batch}) không dùng được với DDP, đặt số cụ thể")

    aug = augmentation_config(args)
    print(
        f"[aug] preset={args.aug_preset} multi_scale={args.multi_scale} "
        + " ".join(f"{k}={v}" for k, v in aug.items())
    )

    model = YOLO(args.model)
    model.train(
        data=str(yaml_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        workers=args.workers,
        project=str(args.project),
        name=args.name,
        exist_ok=True,
        resume=args.resume,
        patience=args.patience,
        cache=False if args.cache == "none" else args.cache,
        seed=args.seed,
        pretrained=True,
        plots=True,
        multi_scale=args.multi_scale,
        **aug,
    )
    metrics = model.val(
        data=str(yaml_path),
        imgsz=args.imgsz,
        device=gpus[0] if gpus else device,  # val không chạy DDP, ghim 1 GPU cho gọn log
        split="val",
        project=str(args.project),  # không truyền thì ultralytics đổ ra ./runs/detect/val
        name=f"{args.name}_val",
        exist_ok=True,
    )
    print(f"[val] mAP50-95={metrics.box.map:.4f} mAP50={metrics.box.map50:.4f}")
    print(f"[done] weights: {Path(args.project) / args.name / 'weights/best.pt'}")


# --------------------------------------------------------------------------- main


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--classes",
        choices=["brand", "industry", "logo"],
        default="brand",
        help="nhãn để detect: 3000 brand / ~10 ngành hàng / 1 lớp 'logo' (mặc định: brand)",
    )
    p.add_argument("--out", default=str(OUT_ROOT), help="thư mục dataset YOLO sinh ra")
    p.add_argument(
        "--val-from",
        choices=["test", "train"],
        default="test",
        help="split parquet dùng làm val (mặc định: test)",
    )
    p.add_argument("--limit", type=int, default=0, help="giới hạn ảnh MỖI shard, 0 = tất cả")
    p.add_argument("--force-export", action="store_true", help="export lại dù cache còn khớp")
    p.add_argument("--export-only", action="store_true", help="chỉ export, không train")
    p.add_argument("--export-workers", type=int, default=min(8, os.cpu_count() or 4))

    p.add_argument(
        "--model", default="yolo11s.pt", help="checkpoint khởi tạo, hoặc last.pt khi resume"
    )
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=16, help="-1 để ultralytics tự chọn theo VRAM")
    p.add_argument("--device", default="auto", help="auto | cpu | mps | 0 | 0,1")
    p.add_argument("--workers", type=int, default=8, help="worker của dataloader")
    p.add_argument("--patience", type=int, default=30)
    p.add_argument("--cache", choices=["none", "ram", "disk"], default="none", help="cache ảnh")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--project", default=str(RUNS_DIR))
    p.add_argument("--name", default="logodet3k")
    p.add_argument("--resume", action="store_true", help="train tiếp từ --model (phải là last.pt)")

    aug = p.add_argument_group(
        "augmentation",
        "mặc định preset 'logo'; mọi cờ dưới đây để trống thì lấy theo preset",
    )
    aug.add_argument(
        "--aug-preset",
        choices=list(AUG_PRESETS),
        default="logo",
        help="logo = default đã chỉnh cho dataset này | ultralytics = y default thư viện "
        "| none = tắt sạch để đo baseline (mặc định: logo)",
    )
    aug.add_argument("--multi-scale", action="store_true", help="đổi imgsz ±50%% giữa các batch")
    for key in ULTRALYTICS_AUG:
        kind = int if key == "close_mosaic" else float
        aug.add_argument(
            f"--{key.replace('_', '-')}",
            type=kind,
            default=None,
            dest=key,
            help=f"logo: {LOGO_AUG[key]} | ultralytics: {ULTRALYTICS_AUG[key]}"
            + (f" (brand/industry: {BRAND_SAFE_AUG[key]})" if key in BRAND_SAFE_AUG else ""),
        )
    return p.parse_args()


def main() -> None:
    if not shard_files("train"):
        sys.exit(f"không thấy file parquet nào trong {DATA_DIR}")
    args = parse_args()

    missing = []
    for module, package in (("pyarrow", "pyarrow"), ("PIL", "pillow")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if not args.export_only:
        try:
            __import__("ultralytics")
        except ImportError:
            missing.append("ultralytics")
    if missing:
        flags = " ".join(f"--with {pkg}" for pkg in missing)
        sys.exit(
            f"thiếu package: {', '.join(missing)}\n  uv run --no-project {flags} {sys.argv[0]}"
        )

    yaml_path, names = export_dataset(args)
    if args.export_only:
        print(f"[export] data.yaml: {yaml_path}")
        return
    train(args, yaml_path, names)


if __name__ == "__main__":
    main()
