#!/usr/bin/env python3
"""定稿原图 / 现有抠图版主图 / 原图直通主图 三方对比（可指定 case）。

验证「白底主图直接用定稿图」能否保住印花、反光与半透明盖件；
两张主图都跑 check_1688 硬校验，指标写 metrics_<case>.json。

  python stage_a/make_white_compare.py --case reflect_02
  python stage_a/make_white_compare.py --case cap_02 --box 180,120,620,700
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "m0"))
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from pipeline import compose, compliance  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--case", default="reflect_02")
ap.add_argument("--box", default="230,230,570,620",
                help="局部放大区域 x0,y0,x1,y1（基于 800×800 主图）")
a = ap.parse_args()
CASE = a.case
BOX = tuple(int(x) for x in a.box.split(","))

inputs = [p for p in (ROOT / "stage_a/inputs").glob(CASE + ".*")
          if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
assert inputs, "找不到输入图：" + CASE
SRC = inputs[0]
CUT = ROOT / "stage_a/results/products" / CASE / "final/main_white.png"
assert CUT.exists(), "找不到抠图版主图：" + str(CUT)
OUT = ROOT / "stage_a/results/white_compare"
OUT.mkdir(parents=True, exist_ok=True)

font_path, _ = compose.find_font()


def F(size):
    return (ImageFont.truetype(font_path, size) if font_path
            else ImageFont.load_default(size=size))


src = Image.open(SRC)
new_img, _ = compose.make_main_white_from_original(src, 800)
new_path = OUT / (CASE + "_original.png")
new_img.save(new_path, quality=95)
cut = Image.open(CUT).convert("RGB")
old_path = OUT / (CASE + "_cutout.png")
cut.save(old_path, quality=95)


def check(p):
    r = compliance.check_image(str(p), "1688-main-white")
    return {"pass": r["pass"], "metrics": r["metrics"],
            "failed": [c["name"] for c in r["checks"] if not c["pass"]]}


metrics = {"case": CASE, "source": SRC.name,
           "cutout": check(old_path), "original": check(new_path)}
(OUT / ("metrics_" + CASE + ".json")).write_text(
    json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

src_show = src.convert("RGBA")
if src_show.getchannel("A").getextrema()[0] < 255:
    bg = Image.new("RGBA", src_show.size, (255, 255, 255, 255))
    bg.alpha_composite(src_show)
    src_show = bg
src_show = src_show.convert("RGB").resize((800, 800), Image.LANCZOS)

CELL, PAD, HEAD = 560, 20, 52
W = CELL * 3 + PAD * 4
top_h = HEAD + CELL
y2 = PAD + top_h + 70
H = y2 + 40 + 780 + 70
board = Image.new("RGB", (W, H), (246, 247, 249))
d = ImageDraw.Draw(board)

panels = [("① 定稿原图（美工交付）", src_show),
          ("② 现有抠图版主图", cut),
          ("③ 原图直通主图（新）", new_img)]
for i, (title, im) in enumerate(panels):
    x = PAD + i * (CELL + PAD)
    y = PAD
    d.rectangle([x, y, x + CELL, y + top_h], fill=(255, 255, 255))
    d.text((x + 14, y + 10), title, fill=(28, 32, 38), font=F(24))
    thumb = im.resize((CELL - 16, CELL - 16), Image.LANCZOS)
    board.paste(thumb, (x + 8, y + HEAD + 8))

d.text((PAD, y2 - 36), "局部放大 · %s（同一坐标 %s）" % (CASE, a.box),
       fill=(28, 32, 38), font=F(26))
for i, (title, im) in enumerate([("② 抠图版", cut), ("③ 原图直通", new_img)]):
    crop = im.crop(BOX).resize((680, 780), Image.LANCZOS)
    x = PAD + i * (680 + PAD)
    d.rectangle([x, y2, x + 680, y2 + 40 + 780], fill=(255, 255, 255))
    d.text((x + 12, y2 + 8), title, fill=(28, 32, 38), font=F(22))
    board.paste(crop, (x, y2 + 40))

d.text((PAD, H - 48),
       "check_1688：抠图版 %s ｜ 原图直通 %s ｜ 主体占比 %.1f%% → %.1f%% ｜ 白底 %.1f%% → %.1f%%"
       % ("PASS" if metrics["cutout"]["pass"] else "FAIL",
          "PASS" if metrics["original"]["pass"] else "FAIL",
          metrics["cutout"]["metrics"]["coverage"] * 100,
          metrics["original"]["metrics"]["coverage"] * 100,
          metrics["cutout"]["metrics"]["white_background"] * 100,
          metrics["original"]["metrics"]["white_background"] * 100),
       fill=(80, 88, 98), font=F(22))
dst = OUT / ("对比_" + CASE + ".png")
board.save(dst)
print("CASE", CASE, "SOURCE", SRC.name)
print("CUTOUT", json.dumps(metrics["cutout"], ensure_ascii=False))
print("ORIGINAL", json.dumps(metrics["original"], ensure_ascii=False))
print("SAVED", new_path)
print("SAVED", dst)
