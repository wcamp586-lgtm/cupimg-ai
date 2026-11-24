#!/usr/bin/env python3
"""在服务器容器内零成本复核排版/标识：不调模型、不花额度、不产生新任务。

用法（本机）：
  ssh -i <key> ubuntu@101.33.74.41 'docker exec -i deploy-api-1 python -' \
      < m0/tools/verify_online_layout.py
会用最近一次真实任务的 cutout / 场景底图 / 文案重排一张 detail 到
/app/data/out/detail_check.png，供回传目视检查。
"""
import glob
import json
import os
import sys

sys.path.insert(0, "/app/m0")
from pipeline import compose, compliance  # noqa: E402
from PIL import Image  # noqa: E402

roots = sorted(glob.glob("/app/m0/out/*/DEMO-PLANET-02"), key=os.path.getmtime)
assert roots, "没有可复用的线上任务产物"
r = roots[-1]
c = json.load(open(os.path.join(r, "evidence/generation_record.json"),
                   encoding="utf-8"))["copy"]
f, ok = compose.find_font()
print("ROOT", r)
print("FONT", f, "| whitelist", ok)

lines, size, truncated = compose.layout_text(c["title"], f, 44, 720, max_lines=2)
print("TITLE", json.dumps(lines, ensure_ascii=False),
      "| size", size, "| truncated", truncated)
assert not any("…" in x for x in lines), "标题仍被硬裁断"
assert not any("316\n" in x or x.endswith("316") for x in lines), "型号被拆行"

label = compliance.ai_label()
prod = Image.open(os.path.join(r, "work/cutout.png")).convert("RGBA")
scene = Image.open(os.path.join(r, "work/scene_bg.png")).convert("RGB")
img = compose.make_detail(scene, prod, {}, c, f, label, 800)
dst = "/app/data/out/detail_check.png"
img.save(dst)

texts = [c["title"], c["subtitle"]] + list(c["bullets"])
res = compliance.check_text_fit(
    texts, f, [(44, 2), (24, 2)] + [(24, 1)] * len(c["bullets"]))
print("TEXT_FIT", json.dumps(res, ensure_ascii=False))
print("AI_LABEL", label["explicit"], "|",
      label["implicit_fields"]["AIGC_Product"])
print("SAVED", dst)
