#!/usr/bin/env python3
"""线上内测站端到端冒烟：登录 → 上传真实定稿图 → live 出图 → 下载 → 校验 → 拼预览。

只跑 1 个任务，不碰 Stage A 门禁状态。用法：
    python m0/tools/smoke_web_e2e.py --image stage_a/inputs/logo_01.png \
        --facts stage_a/inputs/logo_01.json --out demo_run
口令从 deploy/.env.production 读取，不打印、不写日志。
"""
import argparse
import http.cookiejar
import io
import json
import os
import sys
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://cupimg.aicloud.plus"


def load_code():
    for line in (ROOT / "deploy" / ".env.production").read_text(
            encoding="utf-8").splitlines():
        if line.strip().startswith("ACCESS_CODE="):
            return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("deploy/.env.production 里找不到 ACCESS_CODE")


def make_opener():
    cj = http.cookiejar.CookieJar()
    # 本机全局代理会把公网站点引到 502，显式禁用
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(cj))


def post_json(op, path, obj, timeout=30):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post_multipart(op, path, fields, image_path, timeout=90):
    boundary = "----wb" + uuid.uuid4().hex
    buf = io.BytesIO()
    for k, v in fields.items():
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (boundary, k, v)).encode("utf-8"))
    buf.write(("--%s\r\nContent-Disposition: form-data; name=\"image\"; "
               "filename=\"%s\"\r\nContent-Type: image/png\r\n\r\n"
               % (boundary, image_path.name)).encode("utf-8"))
    buf.write(image_path.read_bytes())
    buf.write(b"\r\n")
    buf.write(("--%s--\r\n" % boundary).encode("utf-8"))
    req = urllib.request.Request(
        BASE + path, data=buf.getvalue(), method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_json(op, path, timeout=30):
    with op.open(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_bytes(op, path, timeout=180):
    with op.open(BASE + path, timeout=timeout) as r:
        return r.read()


def cn_font(size):
    from PIL import ImageFont
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def make_preview(out, original):
    """2x2：原图 / 白底主图 / 场景图 / 详情图。"""
    from PIL import Image, ImageDraw, ImageOps
    items = [("原图 · 美工定稿", original),
             ("白底主图 800x800", out / "final" / "main_white.png"),
             ("AI 场景图", out / "final" / "scene.png"),
             ("详情图 / 可编辑稿", out / "final" / "detail.png")]
    cell, pad, head = 560, 24, 46
    board = Image.new("RGB", (cell * 2 + pad * 3, (cell + head) * 2 + pad * 3),
                      (246, 247, 249))
    d = ImageDraw.Draw(board)
    font = cn_font(24)
    for i, (title, p) in enumerate(items):
        x = pad + (i % 2) * (cell + pad)
        y = pad + (i // 2) * (cell + head + pad)
        d.rectangle([x, y, x + cell, y + cell + head], fill=(255, 255, 255))
        d.text((x + 14, y + 8), title, fill=(28, 32, 38), font=font)
        if p.exists():
            im = Image.open(p).convert("RGB")
            im.thumbnail((cell - 16, cell - 8))
            board.paste(im, (x + (cell - im.width) // 2,
                             y + head + (cell - im.height) // 2))
        else:
            d.text((x + 20, y + head + 40), "（缺失）", fill=(180, 60, 60), font=font)
    dst = out.parent / "效果总览.jpg"
    board.save(dst, quality=90)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="stage_a/inputs/logo_01.png")
    ap.add_argument("--facts", default="stage_a/inputs/logo_01.json")
    ap.add_argument("--out", default="demo_run")
    ap.add_argument("--wait", type=int, default=300)
    a = ap.parse_args()

    image = (ROOT / a.image).resolve()
    facts = json.loads((ROOT / a.facts).read_text(encoding="utf-8"))
    out = (ROOT / a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    op = make_opener()
    print("[1/6] 登录 /healthz ...", flush=True)
    print("      ", get_json(op, "/healthz"), flush=True)
    print("[2/6] 口令登录 ...", flush=True)
    print("      ", post_json(op, "/api/login", {"code": load_code()}), flush=True)

    fields = {"sku": "DEMO-" + str(facts["sku"]), "name": facts["name"],
              "material": facts["material"], "capacity_ml": str(facts["capacity_ml"]),
              "color": facts["color"], "dimensions_mm": facts.get("dimensions_mm", ""),
              "logo_text": facts.get("logo_text", ""), "brand": facts.get("brand", ""),
              "shape_note": facts.get("shape_note", ""),
              "has_handle": "true" if facts.get("has_handle") else "false"}
    print("[3/6] 上传 %s (%.1f MB) 提交 live 任务 ..."
          % (image.name, image.stat().st_size / 1048576), flush=True)
    job = post_multipart(op, "/api/jobs", fields, image)
    jid = job["id"]
    print("      job_id =", jid, "| queue_ahead =", job.get("queue_ahead"), flush=True)

    print("[4/6] 轮询管线（最长 %ds）..." % a.wait, flush=True)
    t0, last = time.time(), ""
    while time.time() - t0 < a.wait:
        j = get_json(op, "/api/jobs/" + jid)
        state = "%s step=%s" % (j.get("phase"), j.get("step"))
        if state != last:
            print("      %5.1fs  %s" % (time.time() - t0, state), flush=True)
            last = state
        if j.get("phase") in ("done", "failed"):
            break
        time.sleep(5)
    else:
        raise RuntimeError("轮询超时：%ds 内未结束" % a.wait)
    j = get_json(op, "/api/jobs/" + jid)
    print("      耗时 %.1fs | phase=%s | delivery=%s | assets=%s"
          % (time.time() - t0, j.get("phase"), j.get("delivery_state"),
             ",".join(j.get("assets") or [])), flush=True)
    print("      reason =", j.get("delivery_reason") or "(无)", flush=True)
    if j.get("error"):
        print("      ERROR =", j["error"], flush=True)
    tail = (j.get("log") or [])[-18:]
    print("      --- 管线日志尾部 ---")
    for line in tail:
        print("      " + str(line)[:200])
    (out / "job.json").write_text(json.dumps(j, ensure_ascii=False, indent=2),
                                  encoding="utf-8")

    if j.get("phase") != "done":
        print("RESULT: FAILED（未产出成品）", flush=True)
        return 1

    print("[5/6] 下载 ZIP 并校验 ...", flush=True)
    raw = get_bytes(op, "/api/jobs/" + jid + "/download")
    (out / "delivery.zip").write_bytes(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        bad = z.testzip()
        names = z.namelist()
        z.extractall(out / "unpacked")
    print("      %.1f KB | CRC=%s | %d 个文件: %s"
          % (len(raw) / 1024, "OK" if bad is None else "BAD:" + bad,
             len(names), ", ".join(names)), flush=True)
    u = out / "unpacked"
    for rel in ("delivery.json", "evidence/compliance_report.json",
                "evidence/cost.json", "evidence/ai_disclosure.json"):
        p = u / rel
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            print("      [%s] %s" % (rel, json.dumps(d, ensure_ascii=False)[:420]),
                  flush=True)

    print("[6/6] 生成效果总览 ...", flush=True)
    prev = make_preview(u, image)
    print("      ", prev, flush=True)
    print("RESULT: OK | job=%s | delivery=%s | 预览=%s"
          % (jid, j.get("delivery_state"), prev), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
