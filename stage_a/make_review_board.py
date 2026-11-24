"""把回传的 Stage A 产物生成一页式人眼验收看板。

用法（工作区根目录，需先跑 fetch_results.py）：
    python stage_a/make_review_board.py

产出 stage_a/results/验收看板.html，并把 10 张输入定稿图复制到
stage_a/results/originals/，让整个 results 目录自包含、可直接打包给美工。
"""
import html
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
R = HERE / "results"
IN = HERE / "inputs"

CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#1f2329;--sub:#5b6570;--line:#e3e7eb;
      --accent:#1a5fb4;--warn:#b06000}
*{box-sizing:border-box}
body{margin:0;padding:28px 18px 60px;background:var(--bg);color:var(--ink);
     font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto}
header{background:linear-gradient(135deg,#1a5fb4,#2b7cd3);color:#fff;
       border-radius:14px;padding:24px 30px;margin-bottom:18px}
h1{margin:0 0 8px;font-size:24px}
header p{margin:3px 0;font-size:14px;opacity:.95}
.ribbon{background:#fff7ed;border-left:4px solid var(--warn);padding:12px 16px;
        border-radius:0 8px 8px 0;margin-bottom:18px;font-size:14px}
.case{background:var(--card);border:1px solid var(--line);border-radius:12px;
      padding:18px 22px;margin-bottom:16px;break-inside:avoid}
.hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.cid{font:600 18px Consolas,monospace}
.cat{background:#e8f0fe;color:var(--accent);padding:2px 10px;border-radius:12px;font-size:13px}
.iou{color:var(--sub);font-size:13px;margin-left:auto}
.state{background:#fef3c7;color:#92400e;padding:2px 10px;border-radius:12px;font-size:12px}
.focus{color:var(--sub);font-size:14px;margin-bottom:10px}
img.cmp{width:100%;border:1px solid var(--line);border-radius:8px;display:block}
.zoom{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px}
figure{margin:0;text-align:center}
figure img{max-width:100%;max-height:330px;border:1px solid var(--line);border-radius:8px}
figcaption{color:var(--sub);font-size:12px;margin-top:5px}
.fill{margin-top:10px;color:var(--sub);font-size:12px;background:#f7f8fa;
      padding:7px 10px;border-radius:6px}
code{background:#eceff2;padding:1px 5px;border-radius:4px;font-size:12px}
footer{text-align:center;color:var(--sub);font-size:12px;margin-top:24px}
@media print{body{background:#fff}.case{border:0;box-shadow:none;page-break-inside:avoid}
 header{background:#1a5fb4 !important;-webkit-print-color-adjust:exact}}
"""


def find_input(cid):
    for ext in (".png", ".jpg", ".jpeg"):
        p = IN / (cid + ext)
        if p.is_file():
            return p
    return None


def main():
    cfg = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    score = json.loads((R / "scorecard.json").read_text(encoding="utf-8"))
    res = {r["id"]: r for r in score["results"]}
    orig = R / "originals"
    orig.mkdir(exist_ok=True)

    cards = []
    for c in cfg["cases"]:
        cid = c["id"]
        r = res.get(cid, {})
        p = find_input(cid)
        rel = "originals/" + cid + p.suffix if p else ""
        if p:
            shutil.copy2(p, orig / (cid + p.suffix))
        cards.append("""
<section class="case">
  <div class="hd"><span class="cid">%s</span><span class="cat">%s</span>
    <span class="iou">轮廓 IoU %s</span><span class="state">待填</span></div>
  <div class="focus">重点看：%s</div>
  <img class="cmp" src="compare/%s.png" alt="%s 三栏对比">
  <div class="zoom">
    <figure><img src="%s" alt="原图"><figcaption>输入定稿图（放大看细节）</figcaption></figure>
    <figure><img src="products/%s/final/main_white.png" alt="成品"><figcaption>AI 成品主图 800×800</figcaption></figure>
  </div>
  <div class="fill">填 <code>review_sheet.csv</code>：主体形变 / Logo变字 / 提环杯盖结构 / 反光结构 / 结论 / 备注</div>
</section>""" % (html.escape(cid), html.escape(c["category"]),
                 html.escape(str(r.get("iou", "-"))), html.escape(c.get("focus", "")),
                 cid, cid, rel, cid))

    doc = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stage A 人眼验收看板 · 10 SKU</title>
<style>%s</style></head><body><div class="wrap">
<header><h1>Stage A 人眼验收看板 · 10 SKU</h1>
<p>自动项 10/10 ｜ 累计 0.0623 元 ｜ 生产级 isnet 抠图 ｜ 2026-11-08</p>
<p><strong>门禁状态 PENDING_HUMAN</strong>：自动项全过 ≠ 图能用，0 容忍形变必须人眼裁定。</p></header>
<div class="ribbon"><strong>禁止直接上架 1688。</strong> 三栏对比图：左=输入定稿图，中=AI 成品主图，
右=轮廓叠影（灰重合 / 红原图独有 / 青成品独有）。IoU 仅参考，白色印花、金属高光、
提环内孔、半透明盖件会造成噪点，不要据此直接判 FAIL。填表说明见《StageA_人眼验收指引_v1》。</div>
%s
<footer>1688 杯具 AI 作图 · Stage A · 形变 0 容忍由人眼最终裁定</footer>
</div></body></html>""" % (CSS, "".join(cards))

    out = R / "验收看板.html"
    out.write_text(doc, encoding="utf-8")
    refs = re.findall(r'src="([^"]+)"', doc)
    missing = [x for x in refs if not (R / x).is_file()]
    print("BOARD_OK %s B | cases=%d | originals=%d | refs=%d | missing=%s" %
          (out.stat().st_size, len(cards), len(list(orig.glob("*"))), len(refs), missing))
    if missing:
        raise SystemExit("看板有缺失图片引用：%s" % missing)


if __name__ == "__main__":
    main()
