#!/usr/bin/env python3
"""接触阴影改前 / 改后对比：用线上真实任务的同一份 cutout + scene_bg。

改前基准 = demo_run4/unpacked/final/scene.png（线上原产物）
改后 = 本地用新 compose.make_scene 重算
同时验证主体区域内像素完全一致，证明商品一个像素都没动。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "m0"))
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from pipeline import compose, compliance  # noqa: E402

SRC = ROOT / "stage_a/results/shadow_compare"
OUT = SRC
OLD = ROOT / "demo_run4/unpacked/final"

cut = Image.open(SRC / "cutout.png").convert("RGBA")
bg = Image.open(SRC / "scene_bg.png").convert("RGB")
copy = json.load(open(SRC / "generation_record.json", encoding="utf-8"))["copy"]
font_path, _ = compose.find_font()
label = compliance.ai_label()

new_scene, box = compose.make_scene(bg, cut, 800)
new_detail = compose.make_detail(bg, cut, {}, copy, font_path, label, 800)
new_scene.save(OUT / "scene_after.png", quality=95)
new_detail.save(OUT / "detail_after.png", quality=95)
old_scene = Image.open(OLD / "scene.png").convert("RGB")
old_detail = Image.open(OLD / "detail.png").convert("RGB")

# 主体区域像素一致性校验
prod = compose._fit_product(cut, (800, 800), 0.70)
alpha = prod.getchannel("A")
opaque = Image.new("L", (800, 800), 0)
opaque.paste(alpha.point(lambda v: 255 if v == 255 else 0), (box[0], box[1]))
semi = Image.new("L", (800, 800), 0)
semi.paste(alpha.point(lambda v: 255 if 0 < v < 255 else 0), (box[0], box[1]))
mo, ms = np.array(opaque) > 0, np.array(semi) > 0
a = np.array(old_scene).astype(int)
b = np.array(new_scene).astype(int)
print("BOX", box)
print("主体不透明区像素完全一致 :", np.array_equal(a[mo], b[mo]),
      "| 最大通道差", int(np.abs(a[mo] - b[mo]).max()))
print("半透明边缘区平均差(阴影透过属正常) :",
      round(float(np.abs(a[ms] - b[ms]).mean()), 2))
print("全图平均绝对差       :", round(float(np.abs(a - b).mean()), 3))


def F(sz):
    return (ImageFont.truetype(font_path, sz) if font_path
            else ImageFont.load_default(size=sz))


CELL, PAD, HEAD = 560, 20, 52
W, top_h = CELL * 2 + PAD * 3, HEAD + CELL
y2 = PAD + top_h + 70
H = y2 + 40 + 300 + 70
board = Image.new("RGB", (W, H), (246, 247, 249))
d = ImageDraw.Draw(board)
for i, (title, im) in enumerate([("① 改前 · 线上原场景图（悬浮）", old_scene),
                                  ("② 改后 · 加接地阴影", new_scene)]):
    x = PAD + i * (CELL + PAD)
    d.rectangle([x, PAD, x + CELL, PAD + top_h], fill=(255, 255, 255))
    d.text((x + 14, PAD + 10), title, fill=(28, 32, 38), font=F(24))
    board.paste(im.resize((CELL - 16, CELL - 16), Image.LANCZOS),
                (x + 8, PAD + HEAD + 8))

d.text((PAD, y2 - 36), "杯底局部放大 · 同一坐标（看接地是否自然）",
       fill=(28, 32, 38), font=F(26))
crop_box = (220, 560, 580, 710)
for i, (title, im) in enumerate([("① 改前", old_scene), ("② 改后", new_scene)]):
    patch = im.crop(crop_box).resize((560, 300), Image.LANCZOS)
    x = PAD + i * (CELL + PAD)
    d.rectangle([x, y2, x + CELL, y2 + 40 + 300], fill=(255, 255, 255))
    d.text((x + 12, y2 + 8), title, fill=(28, 32, 38), font=F(22))
    board.paste(patch, (x, y2 + 40))

d.text((PAD, H - 48),
       "阴影只作用于背景层；白底主图不加阴影；商品主体像素零改动。",
       fill=(80, 88, 98), font=F(22))
dst = OUT / "对比.png"
board.save(dst)
print("SAVED", dst)
print("SAVED", OUT / "scene_after.png")
print("SAVED", OUT / "detail_after.png")
