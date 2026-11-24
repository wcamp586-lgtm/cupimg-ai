"""合规四件套（导出前强制）：极限词 / AI 标识 / 1688 图规 / 字体白名单。

对应《落地执行方案 v1》§04。任一硬项 FAIL 即不得导出交付目录。
"""
import os
import sys

VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)
from check_main_image import check_1688  # MIT, xianyu110/ecommerce-image-skills

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def load_words():
    words = []
    with open(os.path.join(DATA, "forbidden_words.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                words.append(line)
    return words


def load_font_whitelist():
    with open(os.path.join(DATA, "fonts.whitelist.txt"), encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]


def check_words(texts):
    words = load_words()
    hits = []
    for t in texts:
        if not t:
            continue
        for w in words:
            if w in str(t):
                hits.append({"word": w, "context": str(t)[:80]})
    return {"pass": len(hits) == 0, "hits": hits,
            "detail": f"扫描 {len(texts)} 段文本 / {len(words)} 个词条，命中 {len(hits)} 处"}


def check_font(font_path):
    wl = load_font_whitelist()
    ok = bool(font_path) and any(k.lower() in os.path.basename(font_path).lower() for k in wl)
    return {"pass": ok, "font": font_path,
            "detail": ("使用白名单可商用字体" if ok else
                       "未找到白名单字体；当前为链路验证用的系统字体，禁止用于商用出图")}


def check_image(path, label):
    return check_1688(path)


def check_text_fit(texts, font_path, text_specs=None, max_width=720):
    """文字越界硬校验：按各文案实际基准字号复核排版后的每一行。

    排版层已改为「自动降字号 + 折行」而不是截断，所以这里必须调用同一份
    layout_text，否则合规报告会与 PNG/SVG 实际结果不一致。
    text_specs 按位置给出 (基准字号, 允许行数)，默认按最大字号保守检查。
    """
    from PIL import Image, ImageDraw
    from . import compose
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    specs = text_specs or [(44, 2)] * len(texts)
    truncated, overflow = [], []
    for i, t in enumerate(texts):
        if not t:
            continue
        original = str(t).replace("\n", " ").strip()
        base, max_lines = specs[i] if i < len(specs) else (44, 2)
        lines, size, was_truncated = compose.layout_text(
            original, font_path, base, max_width, max_lines=max_lines)
        if was_truncated:
            truncated.append(original[:24])
        font = compose._font(font_path, size)
        for line in lines:
            if probe.textlength(line, font=font) > max_width:
                overflow.append(line[:24])
    return {"pass": not overflow,
            "overflow": overflow, "truncated": truncated,
            "detail": (f"按各文案基准字号/最大宽度 {max_width}px 校验 "
                       f"{len([t for t in texts if t])} 段文案；自动缩排折行，"
                       f"硬裁断 {len(truncated)} 段，越界 {len(overflow)} 段")}


def ai_label(mode="metadata", scene_flow="paste"):
    """《人工智能生成合成内容标识办法》2025-09-01 施行。

    显式标识与 1688 主图「无文字水印」规则存在冲突，因此默认放在
    场景图/详情图 + 披露文件，主图保持干净；正式上线前按平台现行规则确认落位。
    scene_flow=i2i 时主体经 AI 重渲染（非像素原样），文案必须如实区分。
    """
    if scene_flow == "i2i":
        return {
            "mode": mode,
            "explicit": "AI 辅助生成 · 场景重新渲染，商品外观经一致性校验",
            "explicit_on": ("scene/detail + AI_DISCLOSURE.txt" if mode == "metadata"
                            else "scene/detail 角标 + AI_DISCLOSURE.txt"),
            "implicit_fields": {
                "AIGC": "true",
                "AIGC_Label": "AI-assisted-scene-rerender",
                "AIGC_Product": "ai-rerendered-shape-verified",
                "AIGC_Tool": "1688-cup-image-pipeline/m0",
                "AIGC_Disclosure": "AI_DISCLOSURE.txt",
            },
            "legal_note": "隐式标识写入 PNG 元数据；显式标识与存证记录留存不少于 6 个月",
            "conflict": "1688 主图禁止文字水印 → 显式标识暂不落在第 1 张主图（主图仍为原图直通），上线前需按商家后台规则确认",
        }
    return {
        "mode": mode,
        # 输入是美工定稿的白底/透明底成品图，不一定是相机实拍原片；
        # 表述只承诺「主体沿用原图未改动」，不冒充实拍，避免不实描述。
        "explicit": ("AI 辅助生成 · 商品主体沿用原图未改动"),
        "explicit_on": ("scene/detail + AI_DISCLOSURE.txt" if mode == "metadata"
                        else "scene/detail 角标 + AI_DISCLOSURE.txt"),
        "implicit_fields": {
            "AIGC": "true",
            "AIGC_Label": "AI-assisted-scene-only",
            "AIGC_Product": "original-subject-preserved",
            "AIGC_Tool": "1688-cup-image-pipeline/m0",
            "AIGC_Disclosure": "AI_DISCLOSURE.txt",
        },
        "legal_note": "隐式标识写入 PNG 元数据；显式标识与存证记录留存不少于 6 个月",
        "conflict": "1688 主图禁止文字水印 → 显式标识暂不落在第 1 张主图，上线前需按商家后台规则确认",
    }


# i2i 直出形变门禁（2026-11-24 定调：0 容忍从「像素未改动」改为「对齐后无形变」）
SCENE_IOU_MIN = 0.95      # bbox 对齐后整体轮廓 IoU 下限
SCENE_REGION_IOU_MIN = 0.85   # 上/中/下三段分区 IoU 下限（防缺件）
SCENE_COLOR_DIFF_MAX = 25.0   # 主体区各通道均值差上限（255 制，实测好例 ≈7）
SCENE_ASPECT_TOL = 0.10   # 主体 bbox 长宽比偏差容差（防非等比压扁/拉伸）


def check_scene_shape(orig_rgba, composed_img, out_rgba, iou_min=None):
    """i2i 直出的商品主体一致性门禁（自动，0 元）。

    模型会重构图（缩放/位移），所以形变判定必须先做 bbox 对齐：
    抠出输入主体与输出主体两副轮廓，把输出裁剪缩放到输入 bbox 尺寸后比对。
    - aligned IoU          ≥ SCENE_IOU_MIN        整体形状
    - 上/中/下三段分区 IoU ≥ SCENE_REGION_IOU_MIN  防缺件（挂绳/提环/杯底）
    - 主体区各通道均值差   ≤ SCENE_COLOR_DIFF_MAX 防改色
    任一不过 → FAIL，交付降级 NEEDS_REVIEW。
    """
    import numpy as np
    from PIL import Image
    iou_min = iou_min or SCENE_IOU_MIN
    # 统一坐标系：以输出画面（composed）为基准。原图产物可能远大于输出
    # （如 3000px 定稿图），bbox_out 供详情图裁剪用，必须在输出坐标系下。
    if orig_rgba.size != composed_img.size:
        orig_rgba = orig_rgba.resize(composed_img.size, Image.LANCZOS)
    if out_rgba.size != composed_img.size:
        out_rgba = out_rgba.resize(composed_img.size, Image.LANCZOS)
    mo = np.array(orig_rgba.getchannel("A")) > 128
    mn = np.array(out_rgba.getchannel("A")) > 128

    def _bbox(m):
        ys, xs = np.where(m)
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    try:
        b1, b2 = _bbox(mo), _bbox(mn)
    except ValueError:
        return {"pass": False, "detail": "轮廓为空：抠图失败，无法判定主体一致性"}

    sub = Image.fromarray((mn * 255).astype("uint8")).crop(b2)
    aligned = Image.new("L", mo.shape[::-1], 0)
    w1, h1 = b1[2] - b1[0], b1[3] - b1[1]
    aligned.paste(sub.resize((w1, h1), Image.LANCZOS), (b1[0], b1[1]))
    ma = np.array(aligned) > 128

    iou = float((mo & ma).sum() / max(1, (mo | ma).sum()))
    h3 = h1 // 3
    regions = {}
    for name, sl in (("上段(含挂绳/提环)", slice(b1[1], b1[1] + h3)),
                     ("中段(杯身)", slice(b1[1] + h3, b1[1] + 2 * h3)),
                     ("下段(杯底)", slice(b1[1] + 2 * h3, b1[3]))):
        a, b = mo[sl], ma[sl]
        regions[name] = round(float((a & b).sum() / max(1, (a | b).sum())), 4)
    region_ok = all(v >= SCENE_REGION_IOU_MIN for v in regions.values())

    scale = (round((b2[2] - b2[0]) / max(1, w1), 3),
             round((b2[3] - b2[1]) / max(1, h1), 3))
    # 长宽比偏差：bbox 对齐会把非等比形变归一化掉，用外接框长宽比单独拦
    aspect_ratio = ((b2[2] - b2[0]) / max(1, b2[3] - b2[1])) / max(1e-6, w1 / max(1, h1))
    aspect_ok = abs(aspect_ratio - 1.0) <= SCENE_ASPECT_TOL
    # 颜色：输入主体 vs 输出主体所在画面区域
    o_rgb = np.array(orig_rgba.convert("RGB")).astype(float)[mo]
    c_rgb = np.array(composed_img.convert("RGB")).astype(float)[mn]
    color_diff = [round(float(x), 1) for x in np.abs(o_rgb.mean(axis=0) - c_rgb.mean(axis=0))]
    color_ok = bool(max(color_diff) <= SCENE_COLOR_DIFF_MAX)

    passed = iou >= iou_min and region_ok and color_ok and aspect_ok
    return {"pass": passed,
            "iou_aligned": round(iou, 4), "iou_min": iou_min,
            "regions": regions, "region_min": SCENE_REGION_IOU_MIN,
            "output_scale": scale, "bbox_in": list(b1), "bbox_out": list(b2),
            "aspect_ratio": round(float(aspect_ratio), 4),
            "aspect_tol": SCENE_ASPECT_TOL,
            "color_diff": color_diff,
            "color_max": SCENE_COLOR_DIFF_MAX,
            "detail": (f"对齐 IoU {iou:.4f}（≥{iou_min}）；"
                       f"分区 " + " ".join(f"{k}={v}" for k, v in regions.items()) +
                       f"；输出构图 {scale[0]}×{scale[1]}（长宽比偏差 "
                       f"{abs(aspect_ratio-1)*100:.1f}%，≤{SCENE_ASPECT_TOL*100:.0f}%）；"
                       f"颜色均值差 {color_diff}（≤{SCENE_COLOR_DIFF_MAX}）"
                       + ("" if passed else " → 未过线，需人工复核"))}


def run_all(image_checks, copy_texts, font_path, ledger, label_mode="metadata",
            text_specs=None, scene_check=None, scene_flow="paste"):
    items = {
        "forbidden_words": check_words(copy_texts),
        "text_fit": check_text_fit(copy_texts, font_path, text_specs),
        "font_license": check_font(font_path),
        "ai_label": ai_label(label_mode, scene_flow),
        "image_rules": image_checks,
        "budget": {"pass": not ledger.over_cap,
                   "detail": f"累计 {ledger.total} 元 / 上限 {ledger.cap} 元"},
        "call_status": {"pass": all(c["status"] in ("OK", "STUB") for c in ledger.calls),
                        "detail": "存在 UNKNOWN 调用，需人工确认是否已计费，禁止自动重发"
                        if any(c["status"] not in ("OK", "STUB") for c in ledger.calls)
                        else "全部调用状态明确"},
    }
    hard = ["forbidden_words", "text_fit", "font_license", "image_rules", "budget", "call_status"]
    if scene_check is not None:      # i2i 直出时主体一致性也是硬项
        items["scene_shape"] = scene_check
        hard.append("scene_shape")
    failed = [k for k in hard if not items[k]["pass"]]
    return {"pass": len(failed) == 0, "failed": failed, "items": items}
