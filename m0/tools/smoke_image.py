#!/usr/bin/env python3
"""用已开通的百炼 Key 真实生成 1 张场景图（消耗 1 张免费额度，0 元）。

目的：验证「不注册 BytePlus 也能把 live 全链路跑通」这条备选路线。
安全：不打印 Key；URL 里的临时签名只截取前 60 字符，不落盘。
"""
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "live_scene"
OUT.mkdir(parents=True, exist_ok=True)


def load_env(p):
    env = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


env = load_env(ROOT / ".env")
key = env.get("DASHSCOPE_API_KEY", "")
base = env.get("DASHSCOPE_BASE", "").rstrip("/")
model = env.get("IMAGE_MODEL", "qwen-image-3.0")
if not key or not base:
    print("SMOKE_IMAGE=FAIL | 缺少 DASHSCOPE_API_KEY / DASHSCOPE_BASE")
    sys.exit(1)

# 只生成「空场景」，商品主体由本地抠图后合成，避免 AI 改动产品长相
prompt = (
    "电商产品摄影布景，浅灰米色微水泥桌面，背景是柔和的米白色墙面与一束淡淡的"
    "午后侧光，右后方有一片虚化的绿植轮廓，整体干净、高级、留白充足，"
    "画面中央留出大面积空白用于摆放商品，真实相机拍摄质感，柔和阴影，低饱和。"
    "画面中不要出现任何杯子、瓶罐、器物、文字、logo、人物或水印。"
)
payload = {
    "model": model,
    "prompt": prompt,
    "negative_prompt": "杯子, 水杯, 瓶, 商品, 文字, 字幕, logo, 水印, 人物, 畸变, 杂乱",
    "size": "1024x1024",
    "n": 1,
    "watermark": False,
}
req = urllib.request.Request(
    base + "/images/generations",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode("utf-8"))
        req_id = r.headers.get("x-request-id", "")
except urllib.error.HTTPError as e:
    print("HTTP=" + str(e.code) + " | " + e.read().decode("utf-8", "replace")[:400])
    print("SMOKE_IMAGE=FAIL")
    sys.exit(1)
except Exception as e:
    print("ERROR=" + repr(e)[:300])
    print("SMOKE_IMAGE=FAIL")
    sys.exit(1)

if "error" in d:
    print("API_ERROR=" + json.dumps(d["error"], ensure_ascii=False)[:300])
    print("SMOKE_IMAGE=FAIL")
    sys.exit(1)

items = d.get("data") or []
if not items:
    print("NO_IMAGE_IN_RESPONSE=" + json.dumps(d, ensure_ascii=False)[:300])
    print("SMOKE_IMAGE=FAIL")
    sys.exit(1)

url = items[0].get("url") or ""
b64 = items[0].get("b64_json") or ""
if b64:
    import base64
    raw = base64.b64decode(b64)
elif url:
    with urllib.request.urlopen(url, timeout=120) as r:
        raw = r.read()
else:
    print("NO_URL_NO_B64")
    print("SMOKE_IMAGE=FAIL")
    sys.exit(1)

from PIL import Image  # noqa: E402
im = Image.open(io.BytesIO(raw)).convert("RGB")
dest = OUT / ("scene_" + model.replace(".", "-") + ".png")
im.save(dest)
print("HTTP=200 | MODEL=" + model + " | REQUEST_ID=" + req_id)
print("USAGE=" + json.dumps(d.get("usage", {}), ensure_ascii=False))
print("IMAGE_SIZE=" + str(im.size) + " | BYTES=" + str(len(raw)))
print("SAVED=m0/out/live_scene/" + dest.name)
print("SMOKE_IMAGE=PASS")
