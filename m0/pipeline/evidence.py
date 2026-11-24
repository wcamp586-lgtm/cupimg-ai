"""存证与交付层：底图哈希、模型版本、prompt、费用、校验、三态交付。

即使 M0 是一次性验证脚本，账本/审计/存证的字段形状也按 SaaS 标准定义，
M3 建库时可直接映射成表，不用回改流水线。
"""
import hashlib
import json
import os
import time

from . import compliance as compliance_mod


def _dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write(root, ctx):
    ev = os.path.join(root, "evidence")
    os.makedirs(ev, exist_ok=True)

    scene_flow = ctx.get("scene_flow", "paste")
    i2i = scene_flow == "i2i"
    _dump(os.path.join(ev, "generation_record.json"), {
        "schema_version": "m0-1",
        "tenant_id": ctx["tenant"],
        "sku": ctx["sku"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": ctx["mode"],
        "white_source": ctx.get("white_source", "cutout"),
        "scene_flow": scene_flow,
        "scene_shape": ctx.get("scene_check"),
        "out_cutout_model": ctx.get("out_cut_model", ""),
        "i2i_model": ctx.get("i2i_model", ""),
        "source": {"file": ctx["source_name"], "sha256": ctx["source_sha256"],
                   "exif_stripped": True,
                   "note": ("底图为美工定稿的白底/透明底成品图（非相机原始实拍原片）；"
                            "i2i 直出路线下场景图主体经 AI 重渲染，"
                            "已通过对齐轮廓 IoU + 颜色一致性自动门禁"
                            if i2i else
                            "底图为美工定稿的白底/透明底成品图（非相机原始实拍原片），"
                            "商品主体像素未在 AI 环节被重绘")},
        "facts": ctx["facts"],
        "observed": ctx["observed"],
        "copy": ctx["copy"],
        "model_calls": ctx["ledger"].calls,
        "stub_roles": ctx["adapter"].stub_used,
        "cutout_model": ctx["cutout_model"],
        "compliance": ctx["compliance"],
        "retention_note": "生成记录与底图留存不少于 6 个月（《标识办法》）",
    })

    _dump(os.path.join(ev, "cost.json"), {
        "currency": "CNY",
        "total": ctx["ledger"].total,
        "cap": ctx["ledger"].cap,
        "calls": ctx["ledger"].calls,
        "note": "offline 桩调用计 0 元；live 为按公开单价估算，以控制台账单为准",
    })

    _dump(os.path.join(ev, "compliance_report.json"), ctx["compliance"])

    _dump(os.path.join(root, "design.json"), {
        "schema_version": "m0-1",
        "sku": ctx["sku"],
        "canvas": {"width": 800, "height": 800},
        "scene_flow": scene_flow,
        "layers": [
            {"id": "background", "kind": "scene", "editable": True,
             "note": ("i2i 直出：场景与主体由 Seedream 融合渲染，已过自动形变门禁"
                      if i2i else None)},
            {"id": "product", "kind": "original-image", "editable": False,
             "note": ("主图 1 直接沿用定稿原图，禁止 AI 重绘"
                      if ctx.get("white_source") == "original"
                      else "图实一致：禁止 AI 重绘")},
            {"id": "copy", "kind": "text", "editable": True,
             "text": ctx["copy"]},
        ],
        "assets": {"main_white": "final/main_white.png",
                   "scene": "final/scene.png",
                   "detail": "final/detail.png",
                   "editable": "editable/design.svg"},
    })

    _dump(os.path.join(root, "delivery.json"), {
        "sku": ctx["sku"],
        "pipeline_state": "PIPELINE_OK" if ctx["pipeline_ok"] else "PIPELINE_FAILED",
        "delivery_state": ctx["delivery_state"],
        "reason": ctx["delivery_reason"],
        "ready_assets": ctx["ready_assets"],
        "human_review_required": ctx["delivery_state"] != "READY",
    })

    if i2i:
        disclosure_1 = (
            "1. 场景图/详情图采用 AI 图生图直出：商品主体经 AI 重渲染以融合场景光影，"
            "输出已通过自动一致性门禁（bbox 对齐轮廓 IoU ≥ %.2f、分区 IoU ≥ %.2f、"
            "主体颜色均值差 ≤ %.0f/255），并保留本次门禁数值。主图 1 仍为定稿原图直通，"
            "像素零改动。\n" % (compliance_mod.SCENE_IOU_MIN,
                                compliance_mod.SCENE_REGION_IOU_MIN,
                                compliance_mod.SCENE_COLOR_DIFF_MAX))
        disclosure_2 = "2. AI 参与：场景重渲染（图生图指令编辑）、文案辅助、可见特征识别、门禁校验。\n"
    else:
        disclosure_1 = (
            "1. 商品主体沿用输入的定稿商品图（白底/透明底成品图，非相机原始实拍原片），"
            "未由 AI 重绘，像素原样保留。\n")
        disclosure_2 = "2. AI 仅参与：场景/背景氛围生成、文案辅助、可见特征识别。\n"

    with open(os.path.join(ev, "AI_DISCLOSURE.txt"), "w", encoding="utf-8") as f:
        f.write(
            "AI 生成合成内容披露 / AI Disclosure\n"
            "==========================================\n"
            f"SKU: {ctx['sku']}\n"
            f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"运行模式: {ctx['mode']} | 场景路线: {scene_flow}\n\n"
            + disclosure_1 + disclosure_2 +
            "3. 隐式标识已写入各 PNG 文件元数据（AIGC / AIGC_Label / AIGC_Product）。\n"
            "4. 显式标识位于 detail.png 与 scene 使用说明，主图保持无文字水印。\n"
            "5. 依据：《人工智能生成合成内容标识办法》（2025-09-01 施行）。\n"
            "6. 底图哈希、模型版本、prompt、费用、门禁数值与校验记录见 generation_record.json。\n"
            "7. 正式上架 1688 前，请按商家后台现行图规复核显式标识落位。\n")

    return ev
