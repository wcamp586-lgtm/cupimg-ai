#!/usr/bin/env python3
"""Stage A 门禁：10 SKU 商品定稿图批量验证「商品主体零形变」。

设计口径（对应《落地执行方案 v1》Stage A，2026-11-08 按真实产品结构修订）：
- 在售品类以金属保温杯为主、偶尔塑料杯，**无玻璃产品**（用户确认）。
  玻璃 / 折射 / 双层杯壁专项已从门禁永久移除，不再补测。
- 10 个 SKU：杯盖 / 反光 / 提环 / Logo / 异形 各 2
- 0 容忍主体形变、Logo 变字、提环与杯盖结构变化、金属反光丢失
- 输入为已定稿的商品白底/透明底成品图（用户确认接受，非相机原始实拍原片），
  验的是 AI 不改定稿主体；图实一致由美工既有流程保证，报告不冒充原片。
- 预算 50 元硬上限，累计超限立即停
- ≥7/10 达标才进开发，不过线止损
- **自动项通过 ≠ 过门禁**：形变必须人眼验收，脚本只出对比图与评审表，
  绝不擅自宣布 PASS

额度策略：10 个 SKU 共用一张空场景（--scene-cache）。
场景是无关变量，复用既省生图免费额度（当前仅剩 5 张），也让主体对比更干净。

用法（在工作区根目录执行）：
  python stage_a/run_stage_a.py --init     # 生成 10 个待填 facts 模板（不花钱）
  python stage_a/run_stage_a.py --check    # 只校验输入齐备，不调用任何模型
  python stage_a/run_stage_a.py --run      # 真跑（累计成本护栏）
  python stage_a/run_stage_a.py --report   # 只重新汇总已有结果
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
M0 = ROOT / "m0"
INPUTS = HERE / "inputs"
OUT = HERE / "out"
COMPARE = OUT / "compare"
SCENE_CACHE = HERE / "scene" / "neutral_scene.png"
MANIFEST = HERE / "manifest.json"
IMG_EXT = (".jpg", ".jpeg", ".png")

CATEGORIES = ["杯盖", "反光", "提环", "Logo", "异形"]
CASES = [
    ("cap_01", "杯盖", "方形透明视窗盖、多饮口结构是否丢失或变形"),
    ("cap_02", "杯盖", "半透明塑料盖件的 alpha 边缘是否被抠糊"),
    ("reflect_01", "反光", "纯钛镜面高光是否被抠图吃掉或变脏"),
    ("reflect_02", "反光", "格纹金属杯身与球盖反光边缘是否断裂"),
    ("handle_01", "提环", "提环内孔是否填实、与杯盖连接处是否缺肉"),
    ("handle_02", "提环", "提环与外接挂绳/背带是否丢失或断裂"),
    ("logo_01", "Logo", "杯身小字印字是否变字、糊字、位移"),
    ("logo_02", "Logo", "卡通印花与描边小字是否完整保留"),
    ("shape_01", "异形", "锥形咖啡杯非圆柱轮廓是否走样"),
    ("shape_02", "异形", "三饮盖凸起与杯身衔接处轮廓是否变形"),
]
FACT_KEYS = ["sku", "name", "material", "capacity_ml", "color"]


# ---------------------------------------------------------------- 初始化 / 校验

def init_templates():
    INPUTS.mkdir(parents=True, exist_ok=True)
    (HERE / "scene").mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    COMPARE.mkdir(parents=True, exist_ok=True)
    manifest = {
        "budget_cny": 50.0,
        "scene_cache": "scene/neutral_scene.png",
        "note": "场景为无关变量，10 个 SKU 共用一张空场景做控制变量",
        "cases": [{"id": cid, "category": cat, "focus": focus}
                  for cid, cat, focus in CASES],
    }
    if not MANIFEST.exists():
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    made = 0
    for cid, cat, focus in CASES:
        p = INPUTS / (cid + ".json")
        if p.exists():
            continue
        tpl = {
            "sku": cid.upper().replace("_", "-"),
            "name": "（必填：商品名称，别写极限词）",
            "material": "（必填：材质）",
            "capacity_ml": 350,
            "color": "（必填：颜色）",
            "dimensions_mm": "",
            "logo_text": "（杯身有印字才填，没有留空）",
            "brand": "",
            "shape_note": focus,
            "has_handle": cat in ("提环", "杯盖"),
            "certifications": [],
        }
        p.write_text(json.dumps(tpl, ensure_ascii=False, indent=2), encoding="utf-8")
        made += 1
    if not (INPUTS / "放图说明.txt").exists():
        (INPUTS / "放图说明.txt").write_text(
            "把 10 张已定稿的商品白底/透明底成品图放进本目录，文件名与同名 .json 对应：\n"
            "  cap_01  cap_02  reflect_01  reflect_02  handle_01  handle_02\n"
            "  logo_01  logo_02  shape_01  shape_02\n"
            "扩展名 .jpg / .jpeg / .png 均可，脚本自动识别。\n\n"
            "产品以金属保温杯为主、偶尔塑料杯，无玻璃产品；玻璃专项已从门禁移除。\n"
            "要求：单只杯子、背景干净、无水印无贴字、短边 >= 800px、<= 15MB。\n"
            "同时把同名 .json 里的 5 个必填字段改成真实商品事实（占位文字必须替换）。\n"
            "事实是文案与合规校验的唯一来源，AI 不臆造；缺字段会拒绝出图。\n",
            encoding="utf-8")
    print("INIT: manifest.json + %d 个 facts 模板已写入 %s" % (made, INPUTS))
    print("     接下来把 10 张商品定稿图放进 inputs/，再填同名 json。")


def find_image(cid):
    for ext in IMG_EXT:
        p = INPUTS / (cid + ext)
        if p.is_file():
            return p
    return None


def load_cases():
    if not MANIFEST.exists():
        raise SystemExit("缺少 manifest.json，请先执行 --init")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def check(strict=True):
    cfg = load_cases()
    rows, problems = [], []
    for c in cfg["cases"]:
        cid, cat = c["id"], c["category"]
        img, fp = find_image(cid), INPUTS / (cid + ".json")
        row = {"id": cid, "category": cat, "image": "-", "facts": "-",
               "size": "-", "missing": [], "warn": []}
        if not img:
            row["missing"].append("输入图")
        else:
            row["image"] = img.name
            try:
                with Image.open(img) as im:
                    row["size"] = "%dx%d" % im.size
                    if min(im.size) < 800:
                        row["warn"].append("短边<800px")
            except Exception as e:
                row["missing"].append("图片不可读(%s)" % type(e).__name__)
            if img.stat().st_size > 15 * 1024 * 1024:
                row["warn"].append("超过15MB")
        if not fp.is_file():
            row["missing"].append("facts.json")
        else:
            row["facts"] = "有"
            try:
                f = json.loads(fp.read_text(encoding="utf-8"))
                miss = [k for k in FACT_KEYS if f.get(k) in (None, "", [])]
                row["missing"] += ["字段:" + k for k in miss]
                # 事实层铁律：占位文字按「缺字段」硬拦截，不能只提醒。
                # 否则 --run 会拿「（必填：材质）」当真实事实出图，污染文案与合规校验。
                for k, v in f.items():
                    if isinstance(v, str) and ("必填" in v or "（" in v):
                        row["missing"].append("占位:" + k)
            except Exception as e:
                row["missing"].append("JSON 解析失败(%s)" % type(e).__name__)
        if row["missing"]:
            problems.append("%s: 缺 %s" % (cid, "、".join(row["missing"])))
        rows.append(row)

    print("\n%-13s %-6s %-18s %-11s %-6s %s" %
          ("CASE", "类别", "图片", "尺寸", "事实", "状态"))
    print("-" * 78)
    for r in rows:
        status = "待补: " + "、".join(r["missing"]) if r["missing"] else "OK"
        if r["warn"]:
            status += " | 提醒: " + "、".join(r["warn"])
        print("%-13s %-6s %-18s %-11s %-6s %s" %
              (r["id"], r["category"], r["image"], r["size"], r["facts"], status))
    counts = {cat: sum(1 for r in rows if r["category"] == cat) for cat in CATEGORIES}
    print("-" * 78)
    print("类别分布:", " / ".join("%s %d" % (k, v) for k, v in counts.items()),
          "| 齐备 %d/%d" % (len(rows) - len(problems), len(rows)))
    if any(v != 2 for v in counts.values()) or len(rows) != 10:
        problems.append("必须是 10 个 case 且 5 类各 2")
    if problems and strict:
        print("\nCHECK = BLOCKED（未调用任何模型、未花一分钱）")
        for p in problems:
            print("  -", p)
        return False, rows
    print("\nCHECK = READY" if not problems else "\nCHECK = 有问题")
    return (not problems), rows


# ---------------------------------------------------------------- 对比图

def _fit_canvas(im, size=400, bg=(255, 255, 255)):
    im = im.convert("RGB")
    scale = min(size / im.width, size / im.height)
    nw, nh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
    small = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), bg)
    canvas.paste(small, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def _fill_holes(mask):
    """补回被主体包围的白/高光区域，避免金属高光、白色 Logo 被误判成形变。

    做法：从四角 flood fill 标记「与画布边缘连通的外部背景」，
    剩下未被标记的非零/零像素一律算主体内部（含提环内孔以外的洞）。
    """
    try:
        from scipy import ndimage
        filled = ndimage.binary_fill_holes(np.asarray(mask) > 127)
        return Image.fromarray((filled * 255).astype(np.uint8), "L")
    except ImportError:
        im = mask.convert("L").copy()
        w, h = im.size
        for pt in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if im.getpixel(pt) == 0:
                ImageDraw.floodfill(im, pt, 128, thresh=0)
        arr = np.asarray(im)
        return Image.fromarray(np.where(arr == 128, 0, 255).astype(np.uint8), "L")


def _norm_mask(mask, size=400, fill_holes=False):
    if fill_holes:
        mask = _fill_holes(mask)
    bbox = mask.getbbox()
    if not bbox:
        return Image.new("L", (size, size), 0)
    crop = mask.crop(bbox)
    scale = min((size - 40) / crop.width, (size - 40) / crop.height)
    nw, nh = max(1, int(crop.width * scale)), max(1, int(crop.height * scale))
    small = crop.resize((nw, nh), Image.LANCZOS)
    # 闭运算：填掉白色 Logo 与金属高光造成的内部小空洞，只保留外形轮廓
    small = small.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))
    canvas = Image.new("L", (size, size), 0)
    canvas.paste(small, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def make_compare(root, out_png):
    """三栏：输入定稿图 / 成品主图 / 轮廓叠影（红=原图独有，青=成品独有，灰=重合）。

    仅供人眼快速定位形变，IoU 只是参考值，绝不作为自动判定依据。
    """
    src_p = root / "work" / "source_stripped.jpg"
    main_p = root / "final" / "main_white.png"
    cut_p = root / "work" / "cutout.png"
    if not (src_p.exists() and main_p.exists() and cut_p.exists()):
        return None
    src = _fit_canvas(Image.open(src_p))
    main = _fit_canvas(Image.open(main_p))
    cut = Image.open(cut_p).convert("RGBA")
    m_orig = _norm_mask(cut.getchannel("A"))
    arr = np.asarray(Image.open(main_p).convert("RGB")).astype(np.int16)
    nonwhite = ((255 - arr).max(axis=2) > 18).astype(np.uint8) * 255
    m_out = _norm_mask(Image.fromarray(nonwhite, "L"), fill_holes=True)
    a = np.asarray(m_orig) > 127
    b = np.asarray(m_out) > 127
    overlay = np.full((400, 400, 3), 246, dtype=np.uint8)
    overlay[a & b] = (140, 140, 140)
    overlay[a & ~b] = (220, 45, 45)
    overlay[b & ~a] = (20, 150, 185)
    iou = float((a & b).sum()) / max(float((a | b).sum()), 1.0)

    W, H, BAR = 400, 400, 26
    sheet = Image.new("RGB", (W * 3, H + BAR), (255, 255, 255))
    for i, (im, label) in enumerate([
            (src, "1 ORIGINAL PHOTO"), (main, "2 OUTPUT MAIN"),
            (Image.fromarray(overlay), "3 CONTOUR OVERLAY (red=orig / cyan=out)")]):
        sheet.paste(im, (i * W, BAR))
        d = ImageDraw.Draw(sheet)
        d.rectangle([i * W, 0, i * W + W - 1, BAR - 1], fill=(31, 35, 41))
        d.text((i * W + 8, 7), label, fill=(255, 255, 255))
        if i:
            d.line([(i * W, 0), (i * W, H + BAR)], fill=(210, 214, 220), width=1)
    ImageDraw.Draw(sheet).text((2 * W + 8, H + BAR - 16),
                               "contour IoU = %.3f (reference only)" % iou,
                               fill=(90, 95, 105))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    return round(iou, 4)


# ---------------------------------------------------------------- 批量执行 / 汇总

def result_root(cid, facts_path):
    sku = json.loads(Path(facts_path).read_text(encoding="utf-8")).get("sku", "UNKNOWN")
    return M0 / "out" / "stage_a" / cid / sku


def summarize(cfg):
    results = []
    for c in cfg["cases"]:
        cid = c["id"]
        fp = INPUTS / (cid + ".json")
        root = result_root(cid, fp) if fp.is_file() else None
        r = {"id": cid, "category": c["category"], "focus": c["focus"],
             "pipeline": "-", "delivery": "-", "compliance_failed": "-",
             "cost": 0.0, "iou": "-", "compare": "", "log": ""}
        if root and (root / "delivery.json").is_file():
            d = json.loads((root / "delivery.json").read_text(encoding="utf-8"))
            r["pipeline"] = d.get("pipeline_state", "-")
            r["delivery"] = d.get("delivery_state", "-")
            cp = root / "evidence" / "cost.json"
            if cp.is_file():
                r["cost"] = float(json.loads(cp.read_text(encoding="utf-8")).get("total", 0))
            rp = root / "evidence" / "compliance_report.json"
            if rp.is_file():
                rep = json.loads(rp.read_text(encoding="utf-8"))
                r["compliance_failed"] = ",".join(rep.get("failed", [])) or "无"
            cmp_p = COMPARE / (cid + ".png")
            if cmp_p.is_file():
                r["compare"] = str(cmp_p.relative_to(ROOT)).replace("\\", "/")
            ip = OUT / cid / "iou.txt"
            if ip.is_file():
                r["iou"] = ip.read_text(encoding="utf-8").strip()
            lp = OUT / cid / "run.log"
            if lp.is_file():
                r["log"] = str(lp.relative_to(ROOT)).replace("\\", "/")
        results.append(r)
    return results


def write_reports(cfg, results, stop_reason="", meta=None):
    OUT.mkdir(parents=True, exist_ok=True)
    total = round(sum(r["cost"] for r in results), 4)
    auto = [r for r in results if r["pipeline"] == "PIPELINE_OK"
            and r["delivery"] == "READY" and r["compliance_failed"] == "无"]
    obj = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "budget_cny": cfg.get("budget_cny", 50.0),
        "cost_total_cny": total,
        "cases": len(results),
        "auto_pass_count": len(auto),
        "gate_threshold": ">=7/10 且人眼 0 形变",
        "gate_state": "PENDING_HUMAN",
        "human_review_required": True,
        "note": "自动项通过不等于过门禁；形变/Logo/提环与杯盖/反光必须人眼验收后填 review_sheet.csv",
        "stop_reason": stop_reason,
        "run_meta": meta or {},
        "results": results,
    }
    (OUT / "scorecard.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    lines = [
        "# Stage A 门禁 · 自动项汇总", "",
        "生成时间：%s ｜ 预算 %.0f 元 ｜ 已花 %.4f 元 ｜ 自动项通过 %d/%d" %
        (obj["generated_at"], obj["budget_cny"], total, len(auto), len(results)),
        "抠图模型：%s ｜ 场景：%s" %
        ((meta or {}).get("cutout_model", "见 run.log"),
         (meta or {}).get("scene", "10 SKU 共用一张空场景（控制变量）")), "",
        "> **门禁状态：PENDING_HUMAN**。自动项通过不等于过门禁。"
        "形变 / Logo / 提环与杯盖 / 反光 0 容忍必须人眼验收，填完 `review_sheet.csv` 再判定。", "",
        "| CASE | 类别 | 管线 | 交付 | 合规未过项 | 成本(元) | 轮廓IoU | 人眼验收 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append("| %s | %s | %s | %s | %s | %.4f | %s | 待填 |" %
                     (r["id"], r["category"], r["pipeline"], r["delivery"],
                      r["compliance_failed"], r["cost"], r["iou"]))
    lines += ["", "## 判读说明", "",
              "- 轮廓叠影图在 `stage_a/out/compare/`：灰=重合，红=原图独有，青=成品独有；"
              "两者分离即提示形变。",
              "- IoU 只用于快速排序可疑样本，**白色 Logo / 金属高光 / 半透明盖件会造成噪声，不能作为 0 容忍判定依据**。",
              "- `delivery=READY` 只代表程序硬校验通过，不代表杯子没变形。",
              "- 每个 case 的完整日志在 `stage_a/out/<case>/run.log`。", ""]
    if stop_reason:
        lines += ["## 提前终止", "", stop_reason, ""]
    lines += ["## 判定口径", "",
              "人眼验收 10 张全部填完后：达标数 ≥7 且**形变不合格数 = 0** → 进开发；"
              "否则按预案止损，不继续建站。", ""]
    (OUT / "scorecard.md").write_text("\n".join(lines), encoding="utf-8")
    with open(OUT / "review_sheet.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "类别", "重点看什么", "主体形变(0容忍:无/有)",
                    "Logo变字(无/有/不适用)", "提环杯盖结构(无/有/不适用)",
                    "反光结构(无/有/不适用)", "结论(PASS/FAIL)", "备注"])
        for r in results:
            w.writerow([r["id"], r["category"], r["focus"], "", "", "", "", "", ""])
    return obj


def run(cfg, force=False, only=None):
    ok, _ = check(strict=True)
    if not ok:
        print("\nRUN 已中止：输入未齐备，未花一分钱。")
        return
    budget = float(cfg.get("budget_cny", 50.0))
    cache = (HERE / cfg.get("scene_cache", "scene/neutral_scene.png")).resolve()
    # 本机 .env 默认写 isnet-general-use；权重缺失时 rembg 会静默联网下载并卡死。
    # 这里显式选定本地实存的权重，且 10 个 case 用同一模型，避免引入额外变量。
    # 生产权重 isnet（Apache-2.0，官方 MD5 已校验）优先；缺失才退回 u2netp，
    # 但会在 report 里标注，避免把"抠图模型不够好"误判成"方案路线不行"。
    # 权重目录有两个合法位置：本机开发在 assets/models，服务器容器在
    # data/models（持久卷，生产权重 171MB 不打包进镜像）。两边都优先 isnet。
    model_dirs = [ROOT / "assets" / "models", ROOT / "data" / "models"]
    cut_model = weight = models = None
    for d in model_dirs:
        prod = d / "isnet-general-use.onnx"
        if prod.is_file() and prod.stat().st_size == 178648008:
            cut_model, weight, models = "isnet-general-use", prod, d
            break
    if cut_model is None:
        for d in model_dirs:
            fb = d / "u2netp.onnx"
            if fb.is_file():
                cut_model, weight, models = "u2netp", fb, d
                print("[WARN] 生产抠图权重缺失，退回 u2netp；若门禁因抠图质量不达标，"
                      "先补齐 isnet 再复跑，勿据此判定路线失败")
                break
    if cut_model is None:
        raise SystemExit("缺少抠图权重：任一权重目录下都没有 "
                         "isnet-general-use.onnx 或 u2netp.onnx，Stage A 拒绝开跑")
    child_env = os.environ.copy()
    child_env["REMBG_MODEL"] = cut_model
    child_env["U2NET_HOME"] = str(models)
    print("抠图模型: %s（%s，%.1f MB）" %
          (cut_model, weight.name, weight.stat().st_size / 1024 / 1024))
    spent, stop = 0.0, ""
    for c in cfg["cases"]:
        cid = c["id"]
        if only and cid != only:
            continue
        root = result_root(cid, INPUTS / (cid + ".json"))
        if (root / "delivery.json").is_file() and not force:
            print("[SKIP] %s 已有结果（--force 可重跑）" % cid)
            continue
        img = find_image(cid)
        cmd = [sys.executable, "run.py", "--mode", "live",
               "--tenant", "stage_a/" + cid,
               "--input", str(img), "--facts", str(INPUTS / (cid + ".json")),
               "--scene-cache", str(cache)]
        print("\n" + "=" * 68)
        print("[RUN] %s (%s) | 累计 %.4f / %.0f 元" % (cid, c["category"], spent, budget))
        print("=" * 68, flush=True)
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=str(M0), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=420,
                               env=child_env)
            log = p.stdout + ("\n[STDERR]\n" + p.stderr if p.stderr else "")
        except subprocess.TimeoutExpired as e:
            log = "[TIMEOUT] 超过 420s\n" + ((e.stdout or b"").decode("utf-8", "replace")
                                             if isinstance(e.stdout, bytes) else str(e.stdout or ""))
        (OUT / cid).mkdir(parents=True, exist_ok=True)
        (OUT / cid / "run.log").write_text(log, encoding="utf-8")
        print("\n".join(log.strip().splitlines()[-6:]))
        cp = root / "evidence" / "cost.json"
        if cp.is_file():
            spent += float(json.loads(cp.read_text(encoding="utf-8")).get("total", 0))
        iou = make_compare(root, COMPARE / (cid + ".png"))
        (OUT / cid / "iou.txt").write_text(str(iou if iou is not None else "-"),
                                           encoding="utf-8")
        print("[%s] 用时 %.1fs | 累计 %.4f 元 | 轮廓IoU=%s" %
              (cid, time.time() - t0, spent, iou))
        if spent > budget:
            stop = "累计成本 %.4f 元超过预算 %.0f 元，已在 %s 后停止" % (spent, budget, cid)
            print("[STOP]", stop)
            break
    results = summarize(cfg)
    for r in results:
        cmp_p = COMPARE / (r["id"] + ".png")
        if cmp_p.is_file():
            r["compare"] = str(cmp_p.relative_to(ROOT)).replace("\\", "/")
    obj = write_reports(cfg, results, stop,
                        meta={"cutout_model": cut_model,
                              "scene": "10 SKU 共用 stage_a/scene/neutral_scene.png"})
    print("\nSCORECARD: stage_a/out/scorecard.md | 自动项 %d/%d | 累计 %.4f 元 | 门禁 %s" %
          (obj["auto_pass_count"], obj["cases"], obj["cost_total_cny"], obj["gate_state"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--init", action="store_true", help="生成待填模板")
    ap.add_argument("--check", action="store_true", help="只校验输入，不调用模型")
    ap.add_argument("--run", action="store_true", help="批量真跑")
    ap.add_argument("--report", action="store_true", help="只重新汇总")
    ap.add_argument("--force", action="store_true", help="忽略已有结果重跑")
    ap.add_argument("--only", help="只跑指定 case（试跑用）")
    a = ap.parse_args()
    if a.init:
        init_templates()
        return
    cfg = load_cases()
    if a.run:
        run(cfg, a.force, a.only)
    elif a.report or a.check:
        if a.check:
            check(strict=False)
        obj = write_reports(cfg, summarize(cfg))
        print("REPORT: stage_a/out/scorecard.md | 自动项 %d/%d | 门禁 %s" %
              (obj["auto_pass_count"], obj["cases"], obj["gate_state"]))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
