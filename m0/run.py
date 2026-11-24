#!/usr/bin/env python3
"""一条命令跑通「一张定稿商品图 → 1688 可用成品」全流程（M0 竖切）。

  python run.py                          # 零配置：生成 demo 杯图 + offline 全流程
  python run.py --input 美工定稿图.png    # 用你自己的图
  python run.py --mode live              # 填了 .env 的 Key 后走真实模型
  python run.py --facts my_sku.json      # 换成真实商品事实

产物：out/<tenant>/<sku>/{final,editable,evidence,work,*.json}
"""
import argparse
import json
import os
import sys
import time
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw  # noqa: E402
from pipeline import adapters, compliance, compose, evidence, facts  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "out")


ENV_KEYS = (
    "DASHSCOPE_API_KEY", "DASHSCOPE_BASE", "VL_MODEL", "TEXT_MODEL",
    "IMAGE_MODEL", "SCENE_PROVIDER", "BYTEPLUS_API_KEY", "BYTEPLUS_BASE",
    "SEEDREAM_MODEL", "REMBG_MODEL", "COST_CAP_CNY", "SCENE_IOU_MIN",
)


def load_env():
    """本机读 m0/.env；容器内没有该文件时改从环境变量取（compose env_file 注入）。"""
    env = {}
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    for k in set(list(env) + list(ENV_KEYS)):
        v = os.environ.get(k, env.get(k, ""))
        if v:
            env[k] = v
    return {k: v for k, v in env.items() if v != ""}


def make_demo_cup(path):
    """程序生成的白底 demo 杯图，仅用于验证链路；真实验收必须换美工定稿商品图。"""
    s = 800
    img = Image.new("RGB", (s, s), (255, 255, 255))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 285, 205, 515, 620
    d.rounded_rectangle([x0, y0, x1, y1], radius=26, fill=(56, 118, 168),
                        outline=(30, 74, 112), width=8)
    d.ellipse([x0 + 6, y0 - 26, x1 - 6, y0 + 26], fill=(96, 158, 202),
              outline=(30, 74, 112), width=7)
    d.arc([x1 - 12, 310, x1 + 128, 500], start=270, end=90,
          fill=(30, 74, 112), width=26)
    d.rectangle([x0 + 62, 350, x1 - 62, 420], fill=(255, 255, 255))
    d.text((x0 + 78, 368), "DEMO", fill=(40, 90, 140))
    img.save(path, quality=95)
    return path


def normalize_copy(raw, fallback):
    """live 模型返回可能是 JSON 字符串或带 markdown 包裹，统一成排版所需字段。"""
    if raw.get("stub"):
        return raw
    text = raw.get("raw", "")
    try:
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(cleaned)
        return {"stub": False, "title": data.get("title", fallback["title"]),
                "slogan": data.get("slogan", fallback.get("slogan", "")),
                "subtitle": data.get("subtitle", fallback["subtitle"]),
                "bullets": data.get("bullets", fallback["bullets"])[:4],
                "raw": text}
    except Exception:
        return {"stub": False, "title": fallback["title"],
                "slogan": fallback.get("slogan", ""),
                "subtitle": fallback["subtitle"], "bullets": fallback["bullets"],
                "parse_warning": "模型输出非 JSON，已回退模板文案", "raw": text}


def step(n, text):
    print(f"\n[{n:02d}/10] {text}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", help="美工定稿的白底/透明底成品图；不给则自动生成 demo 杯图")
    ap.add_argument("--facts", help="商品事实 JSON；不给则用 DEMO_FACTS")
    ap.add_argument("--mode", choices=["offline", "live"], default="offline")
    ap.add_argument("--tenant", default="demo")
    ap.add_argument("--ai-label", choices=["metadata", "corner"], default="metadata")
    ap.add_argument("--scene-cache", default="",
                    help="空场景缓存文件：存在则直接复用（不消耗生图额度），"
                         "不存在则本次生成后写入，供后续 SKU 复用。Stage A 控制变量用。")
    ap.add_argument("--white-source", choices=["cutout", "original"], default="original",
                    help="主图 1 来源：original=直接复用定稿白底/透明底原图（默认，不抠图）；"
                         "cutout=抠图后贴白底（Stage A 2026-11-08 存档批次口径）")
    ap.add_argument("--scene-mode", choices=["paste", "i2i"], default="paste",
                    help="场景图路线：paste=AI 生成空场景 + 本地贴图合成（主体像素原样）；"
                         "i2i=Seedream 指令编辑直出（融合更好但主体被重渲染，"
                         "须过对齐 IoU+颜色门禁；Stage A 复跑请保持 paste 口径）")
    ap.add_argument("--scene-style", default="candy3d",
                    choices=["candy3d", "warm", "vibrant", "premium_dark"],
                    help="i2i 场景风格（2026-11-24）：candy3d=糖果色3D卡通渲染（默认，"
                         "参考电商样张定调）；warm=米色亚麻暖光（首版）；"
                         "vibrant=绚丽渐变光斑；premium_dark=深色高级感")
    ap.add_argument("--scene-copy", choices=["off", "on"], default="off",
                    help="场景图促销文案层：on=把 title/subtitle 画成描边贴纸字+白色气泡"
                         "（文字均来自已过广告法校验的文案，默认 off）")
    a = ap.parse_args()

    env = load_env()
    ledger = adapters.CallLedger(float(env.get("COST_CAP_CNY", 10)))
    adapter = adapters.Adapter(a.mode, env, ledger)
    t0 = time.time()
    fact = facts.DEMO_FACTS if not a.facts else facts.load(a.facts)
    sku = fact.get("sku", "UNKNOWN")
    root = os.path.join(OUT, a.tenant, sku)
    for sub in ("final", "editable", "evidence", "work"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)

    print("=" * 68)
    print(f"1688 杯具 AI 作图 · M0 单图竖切 | mode={a.mode} | tenant={a.tenant} | sku={sku}")
    print("=" * 68)

    pipeline_ok, err = True, ""
    try:
        # 01 输入：剥 EXIF、转 RGB、留底图哈希
        step(1, "读原图 → 剥离 EXIF（含 GPS）→ 记录底图哈希")
        src = a.input or make_demo_cup(os.path.join(root, "work", "demo_input.jpg"))
        src_rgba = Image.open(src).copy()   # 保留原始 alpha，供「原图直通」主图使用
        img = src_rgba.convert("RGB")
        stripped = os.path.join(root, "work", "source_stripped.jpg")
        img.save(stripped, quality=95)
        src_hash = evidence.sha256(src)

        # 02 商品事实：硬事实只能来自人工表单
        step(2, "校验商品事实（缺字段即拒绝出图，禁止 AI 臆造）")
        ok, errors, warns = facts.validate(fact)
        print("   facts:", json.dumps(fact, ensure_ascii=False))
        for w in warns:
            print("   [WARN]", w)
        if not ok:
            raise RuntimeError("facts 校验失败: " + "; ".join(errors))

        # 03 看图：只补可见特征，不改 facts
        step(3, f"视觉识别可见特征（live: {env.get('VL_MODEL', 'qwen3-vl-plus')}）")
        observed = adapter.describe(stripped)
        print("   observed:", json.dumps(observed, ensure_ascii=False)[:220])

        # 04 文案
        step(4, f"生成套图文案（live: {env.get('TEXT_MODEL', 'qwen3.7-plus')}）")
        fallback = {"title": f"{fact['name']} {fact['capacity_ml']}ml",
                    "subtitle": f"{fact['material']} · {fact['color']}",
                    "bullets": [f"容量 {fact['capacity_ml']} ml",
                                f"材质 {fact['material']}", f"颜色 {fact['color']}"]}
        copy_text = normalize_copy(adapter.write_copy(fact), fallback)
        print("   copy:", json.dumps(copy_text, ensure_ascii=False)[:220])

        # 05 前置合规：极限词
        step(5, "极限词硬拦截（导出前还会再跑一次全量）")
        pre = compliance.check_words([copy_text.get("title"), copy_text.get("subtitle")]
                                     + list(copy_text.get("bullets", [])))
        print("   ", pre["detail"])
        if not pre["pass"]:
            raise RuntimeError("文案命中广告法风险词: " + json.dumps(pre["hits"], ensure_ascii=False))

        # 06 抠图
        step(6, f"抠出商品主体（live: rembg {env.get('REMBG_MODEL', 'isnet-general-use')}，可商用）")
        product, cut_model = adapter.cutout(img)
        product.save(os.path.join(root, "work", "cutout.png"))
        print("   cutout model:", cut_model)

        # 07 场景：i2i 直出（2026-11-24 起线上路线）或 空场景+贴图合成（Stage A 口径）
        scene_flow, composed, i2i_info = "paste", None, {}
        if a.scene_mode == "i2i":
            step(7, "图生图直出场景（Seedream 指令编辑：融合光影与接触阴影，0.12 元/张）")
            try:
                composed, i2i_info = adapter.edit_scene(img, (800, 800), product_rgba=product,
                                                        style=a.scene_style)
                scene_flow = "i2i"
                print("   i2i:", i2i_info.get("note") or i2i_info.get("model", ""))
                composed.save(os.path.join(root, "work", "scene_i2i.png"))
            except Exception as e:
                print("   [WARN] i2i 失败，降级为空场景+贴图合成:", repr(e)[:160])
        if scene_flow == "paste":
            cache = (a.scene_cache or "").strip()
            if cache and os.path.isfile(cache):
                step(7, "复用已缓存空场景（控制变量，本次不消耗生图额度）")
                scene = Image.open(cache).convert("RGB")
                if scene.size != (800, 800):
                    scene = scene.resize((800, 800), Image.LANCZOS)
                scene_model = "scene-cache / 复用"
                print("   scene cache hit:", os.path.abspath(cache))
            else:
                scene_provider = (env.get("SCENE_PROVIDER") or "auto").strip()
                if scene_provider == "byteplus" or (scene_provider == "auto" and env.get("BYTEPLUS_API_KEY")):
                    scene_model = env.get("SEEDREAM_MODEL", "seedream-4-5-251128") + " / BytePlus"
                else:
                    scene_model = env.get("IMAGE_MODEL", "qwen-image-3.0") + " / 百炼"
                step(7, f"生成场景背景（live: {scene_model}；AI 只画空场景，不碰商品）")
                scene = adapter.generate_scene(
                    "clean studio table scene, soft natural light, neutral warm tones, "
                    "empty center for product placement, no cups, no text, no logo", (800, 800))
                if cache:
                    os.makedirs(os.path.dirname(os.path.abspath(cache)), exist_ok=True)
                    scene.save(cache)
                    print("   scene cache saved:", os.path.abspath(cache))
            scene.save(os.path.join(root, "work", "scene_bg.png"))

        # 08 合成 + 可编辑导出
        step(8, "合成三张成品 + 导出 CDR 可编辑 SVG"
                + ("（i2i 直出：主体经重渲染，跑自动形变门禁）" if scene_flow == "i2i" else "（主体像素原样）"))
        scene_check, out_cut_model = None, ""
        if scene_flow == "i2i":
            if i2i_info.get("cutout") is not None:      # offline 桩：主体位置已知
                out_product, out_cut_model = i2i_info["cutout"], "stub-known-mask"
            else:                                        # live：真实抠 i2i 输出主体
                out_product, out_cut_model = adapter.cutout(composed)
                print("   输出主体抠图:", out_cut_model)
            scene_check = compliance.check_scene_shape(
                product, composed, out_product,
                iou_min=float(env["SCENE_IOU_MIN"]) if env.get("SCENE_IOU_MIN") else None)
            print("   形变门禁:", scene_check["detail"])
        font_path, font_ok = compose.find_font()
        label = compliance.ai_label(a.ai_label, scene_flow)
        meta = dict(label["implicit_fields"])
        meta["AIGC_SourceHash"] = src_hash
        if a.white_source == "original":
            main_white, box1 = compose.make_main_white_from_original(src_rgba, 800)
            print("   main_white: 原图直通（不抠图，保住印花 / 半透明盖件）")
        else:
            main_white, box1 = compose.make_main_white(product, 800)
        if scene_flow == "i2i":
            scene_img = composed
            box2 = tuple(scene_check["bbox_out"])
            detail = compose.make_detail_from_composed(composed, box2, copy_text,
                                                       font_path, label, 800)
        else:
            scene_img, box2 = compose.make_scene(scene, product, 800)
            detail = compose.make_detail(scene, product, fact, copy_text, font_path, label, 800)
        # 场景促销文案层（默认关；文字均来自已过广告法校验的 title/subtitle）
        if a.scene_copy == "on" and font_path and (
                copy_text.get("title") or copy_text.get("subtitle")):
            scene_img = compose.draw_scene_copy(scene_img, copy_text, font_path)
            print("   scene copy: 已叠加描边贴纸字文案层")
        for name, im in (("main_white", main_white), ("scene", scene_img), ("detail", detail)):
            compose.save_png(im, os.path.join(root, "final", f"{name}.png"), meta)
        compose.export_svg(os.path.join(root, "editable", "design.svg"),
                           fact, copy_text, label, 800)
        print(f"   font: {font_path} (白名单={font_ok}) | 主体框 main={box1} scene={box2}")

        # 09 导出前全量合规
        step(9, "导出前合规四件套 + 1688 图规硬验收")
        image_checks = compliance.check_image(os.path.join(root, "final", "main_white.png"),
                                               "1688-main-white")
        bullets = list(copy_text.get("bullets", []))
        texts = [copy_text.get("title"), copy_text.get("slogan") or "",
                 copy_text.get("subtitle")] + bullets
        # 与 compose 的排版口径一一对应：标题/副标题可折 2 行，口号场景大字单行，卖点单行
        text_specs = [(44, 2), (66, 1), (24, 2)] + [(24, 1)] * len(bullets)
        report = compliance.run_all(image_checks, texts, font_path if font_ok else None,
                                    ledger, a.ai_label, text_specs=text_specs,
                                    scene_check=scene_check, scene_flow=scene_flow)
        for c in image_checks["checks"]:
            print(f"   [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}: {c['detail']}")
        print("   汇总 failed:", report["failed"])

        # 10 存证 + 三态交付
        step(10, "写生成存证 / 成本账本 / 三态交付")
        if a.mode == "offline":
            state = "NEEDS_REVIEW"
            reason = ("全链路已跑通，但模型环节为本地桩（0 元）：杯子还原度未经真实模型验证。"
                      "填 .env 的免费额度 Key 后以 --mode live 复跑，方可判断能否上架。")
        elif not report["pass"]:
            if "scene_shape" in report["failed"]:
                # 主体一致性是 0 容忍核心，不降级为 PARTIAL，直接人工复核
                state = "NEEDS_REVIEW"
                reason = "i2i 主体一致性门禁未过线（对齐 IoU / 分区 / 颜色），需人工复核"
            else:
                state = "READY_PARTIAL" if all(
                    report["items"][k]["pass"] for k in ("forbidden_words", "budget", "call_status")
                ) else "NEEDS_REVIEW"
                reason = "存在未通过校验项：" + ", ".join(report["failed"])
        else:
            state, reason = "READY", "全部硬校验通过"
        ctx = dict(tenant=a.tenant, sku=sku, mode=a.mode,
                   white_source=a.white_source, scene_flow=scene_flow,
                   scene_style=a.scene_style, scene_copy=(a.scene_copy == "on"),
                   scene_check=scene_check, out_cut_model=out_cut_model,
                   i2i_model=i2i_info.get("model", ""),
                   source_name=os.path.basename(src),
                   source_sha256=src_hash, facts=fact,
                   observed=facts.merge_observed(fact, observed), copy=copy_text,
                   ledger=ledger, adapter=adapter, cutout_model=cut_model,
                   compliance=report, pipeline_ok=True, delivery_state=state,
                   delivery_reason=reason,
                   ready_assets=["final/main_white.png", "final/scene.png",
                                 "final/detail.png", "editable/design.svg"])
        evidence.write(root, ctx)
    except Exception as e:
        pipeline_ok, err = False, repr(e)
        traceback.print_exc()
        ctx = dict(tenant=a.tenant, sku=sku, mode=a.mode,
                   white_source=a.white_source, scene_flow="error",
                   scene_check=None, out_cut_model="", i2i_model="",
                   source_name="",
                   source_sha256="", facts=fact, observed={}, copy={}, ledger=ledger,
                   adapter=adapter, cutout_model="", compliance={"pass": False, "items": {}},
                   pipeline_ok=False, delivery_state="NEEDS_REVIEW",
                   delivery_reason="流水线异常: " + err, ready_assets=[])
        try:
            evidence.write(root, ctx)
        except Exception:
            pass

    print("\n" + "=" * 68)
    print(f"链路: {'PIPELINE_OK ✅' if pipeline_ok else 'PIPELINE_FAILED ❌'} | "
          f"交付: {ctx['delivery_state']} | 成本: {ledger.total} 元 | "
          f"耗时: {time.time()-t0:.1f}s")
    if err:
        print("错误:", err)
    print("桩环节:", ", ".join(adapter.stub_used) or "无")
    print("产物目录:", root)
    print("=" * 68)
    return 0 if pipeline_ok else 1


if __name__ == "__main__":
    sys.exit(main())
