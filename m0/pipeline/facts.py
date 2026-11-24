"""商品事实层：唯一可信来源是人工表单/美工资料，AI 不得改写。

铁律（对应技术架构报告 v2）：
  - facts = 用户确认的硬事实（材质、容量、尺寸、Logo 文字…）
  - observed = VL 模型看到的可见特征，只能补充，不能覆盖 facts
  - 任何 facts 缺失字段，一律拒绝出图（不臆造）
"""
import json

REQUIRED = ["sku", "name", "material", "capacity_ml", "color"]
ALLOWED = REQUIRED + ["dimensions_mm", "logo_text", "has_handle",
                      "shape_note", "certifications", "brand"]

DEMO_FACTS = {
    "sku": "DEMO-001",
    "name": "双层玻璃杯",
    "material": "高硼硅玻璃",
    "capacity_ml": 350,
    "color": "透明",
    "dimensions_mm": "75×75×145",
    "logo_text": "DEMO",
    "has_handle": True,
    "shape_note": "直筒圆杯带把手",
    "certifications": [],
    "brand": "示例品牌",
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate(facts):
    errors, warnings = [], []
    for key in REQUIRED:
        if facts.get(key) in (None, "", []):
            errors.append(f"missing required fact: {key}")
    unknown = [k for k in facts if k not in ALLOWED]
    if unknown:
        warnings.append(f"unknown fact keys (ignored): {unknown}")
    if facts.get("capacity_ml") is not None:
        try:
            if int(facts["capacity_ml"]) <= 0:
                errors.append("capacity_ml must be positive")
        except (TypeError, ValueError):
            errors.append("capacity_ml must be a number")
    return (len(errors) == 0), errors, warnings


def merge_observed(facts, observed):
    """VL 输出只允许写入 observed 命名空间，绝不覆盖 facts。"""
    return {"facts": facts, "observed": observed, "source": "user_form"}
