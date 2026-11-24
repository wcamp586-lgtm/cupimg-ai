#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# 来源：xianyu110/ecommerce-image-skills / scripts/check_main_image.py
# 许可：MIT（全文见同目录 LICENSE.ecommerce-image-skills.txt）
# 改造：1688 杯具项目 —— 保留 analyse()/fix() 像素分析原逻辑，
#       另加 check_1688() 把判定阈值改为 1688 主图口径（800×800 等）。
#       原 Amazon A+ 参数（min-size 1000 / coverage 0.85）不再作为默认。
# ---------------------------------------------------------------------------
"""Check (and optionally fix) an Amazon-style white-background main image.

  python check_main_image.py image.png [--min-coverage 0.85] [--min-size 1000] [--tolerance 3] [--fix fixed.png] [--json]

Checks
  white_background : share of a border band (outer 2%) whose pixels are within `tolerance` of #FFFFFF  (PASS ≥ 0.98)
  exact_ffffff     : share of detected background pixels that are exactly 255,255,255 (informational, aim ≥ 0.95)
  coverage         : longest side of the product bounding box ÷ matching image side             (PASS ≥ min-coverage)
  size             : longest image side in px                                                   (PASS ≥ min-size; 1600+ recommended)

--fix snaps near-white background pixels to pure #FFFFFF and re-crops/pads so the product covers ~87%, square canvas.
Requires: pillow, numpy
"""
import argparse, json, sys

try:
    import numpy as np
    from PIL import Image
except ImportError:
    sys.exit("pip install pillow numpy")


def analyse(img, tolerance=3, product_threshold=12):
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    h, w, _ = rgb.shape
    dist = 255 - rgb.min(axis=2)               # 0 = pure white
    near_white = dist <= tolerance
    band = max(2, int(round(min(h, w) * 0.02)))
    border = np.zeros((h, w), bool)
    border[:band, :] = border[-band:, :] = True
    border[:, :band] = border[:, -band:] = True
    white_bg = float(near_white[border].mean())

    product = dist > product_threshold          # anything clearly not white
    ys, xs = np.where(product)
    if len(xs) == 0:
        return dict(width=w, height=h, white_background=white_bg, exact_ffffff=1.0, coverage=0.0, bbox=None)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    coverage = max(bw / w, bh / h)
    bg_mask = np.ones((h, w), bool)
    bg_mask[y0:y1 + 1, x0:x1 + 1] = False
    exact = float((dist[bg_mask] == 0).mean()) if bg_mask.any() else 0.0  # no background found
    return dict(width=w, height=h, white_background=white_bg, exact_ffffff=exact,
                coverage=float(coverage), bbox=[x0, y0, x1, y1])


def fix(img, bbox, out, tolerance=8, target=0.87):
    rgb = np.asarray(img.convert("RGB")).copy()
    dist = 255 - rgb.min(axis=2)
    rgb[dist <= tolerance] = 255
    im = Image.fromarray(rgb)
    if bbox:
        x0, y0, x1, y1 = bbox
        im = im.crop((x0, y0, x1 + 1, y1 + 1))
    side = int(round(max(im.size) / target))
    side = max(side, 1000)
    scale = side * target / max(im.size)
    if scale > 1:  # upscale small images so the canvas reaches 1000+ px
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        side = int(round(max(im.size) / target))
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    canvas.save(out, quality=95)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--min-coverage", type=float, default=0.85)
    ap.add_argument("--min-size", type=int, default=1000)
    ap.add_argument("--tolerance", type=int, default=3, help="max distance from 255 counted as white (0 = exact)")
    ap.add_argument("--fix", metavar="OUT")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    img = Image.open(a.image)
    r = analyse(img, a.tolerance)
    longest = max(r["width"], r["height"])
    checks = {
        "white_background": (r["white_background"] >= 0.98, f"{r['white_background']:.1%} of border pixels are white (≤{a.tolerance} from #FFFFFF)"),
        "exact_ffffff": (r["exact_ffffff"] >= 0.95, f"{r['exact_ffffff']:.1%} of background is exactly #FFFFFF"),
        "coverage": (r["coverage"] >= a.min_coverage, f"product covers {r['coverage']:.1%} of the frame (need ≥{a.min_coverage:.0%})"),
        "size": (longest >= a.min_size, f"longest side {longest}px (need ≥{a.min_size}; 1600+ recommended for zoom)"),
    }
    ok = all(v[0] for k, v in checks.items() if k != "exact_ffffff")
    if a.json:
        print(json.dumps({"pass": ok, **{k: {"pass": v[0], "detail": v[1]} for k, v in checks.items()}, "bbox": r["bbox"]}, ensure_ascii=False, indent=2))
    else:
        for k, (p, d) in checks.items():
            tag = "PASS" if p else ("WARN" if k == "exact_ffffff" else "FAIL")
            print(f"[{tag}] {k:17s} {d}")
        print("RESULT:", "PASS" if ok else "FAIL")
    if a.fix:
        print("fixed ->", fix(img, r["bbox"], a.fix))
    sys.exit(0 if ok else 1)


def check_1688(image_path, min_size=800, min_coverage=0.60, max_coverage=0.94):
    """1688 主图硬验收（阈值以商家后台现行规则为准，此处为可修改基线）。

    复用本文件 MIT 的 analyse() 像素分析：白底占比、主体包围盒占比、尺寸。
    返回 {pass, checks:[{name,pass,detail,severity}], metrics:{...}}
    """
    img = Image.open(image_path)
    r = analyse(img, tolerance=3)
    w, h = r["width"], r["height"]
    longest, shortest = max(w, h), min(w, h)
    # 本文件原本没 import os，补一个局部导入，保持上游代码零改动
    import os as _os
    size_bytes = _os.path.getsize(image_path)

    checks = [
        dict(name="square_canvas", **{"pass": w == h},
             detail=f"{w}x{h}（1688 主图要求正方形，按商家后台现行规则核实）", severity="FAIL"),
        dict(name="min_size", **{"pass": shortest >= min_size},
             detail=f"短边 {shortest}px（需 ≥{min_size}px）", severity="FAIL"),
        dict(name="format_rgb", **{"pass": img.mode in ("RGB", "RGBA")},
             detail=f"色彩模式 {img.mode}", severity="FAIL"),
        dict(name="white_background", **{"pass": r["white_background"] >= 0.98},
             detail=f"边缘白底占比 {r['white_background']:.1%}（需 ≥98%）", severity="FAIL"),
        dict(name="subject_coverage", **{"pass": min_coverage <= r["coverage"] <= max_coverage},
             detail=f"主体占比 {r['coverage']:.1%}（合理区间 {min_coverage:.0%}–{max_coverage:.0%}）",
             severity="FAIL"),
        dict(name="file_size", **{"pass": size_bytes <= 3 * 1024 * 1024},
             detail=f"{size_bytes/1024:.0f} KB（≤3 MB 基线）", severity="WARN"),
    ]
    return {
        "pass": all(c["pass"] for c in checks if c["severity"] == "FAIL"),
        "checks": checks,
        "metrics": {"width": w, "height": h, "bytes": size_bytes,
                    "white_background": r["white_background"],
                    "coverage": r["coverage"], "bbox": r["bbox"]},
    }


if __name__ == "__main__":
    main()
