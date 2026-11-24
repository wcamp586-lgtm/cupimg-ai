"""容器内 i2i 请求体大小分级实验（只写控制台，产物不入库）。"""
import base64
import io
import json
import os
import time
import urllib.request

from PIL import Image

src = Image.open("/app/data/jobs/20261124-141744-979127/input.jpg").convert("RGB")
KEY = os.environ["BYTEPLUS_API_KEY"]
BASE = os.environ["BYTEPLUS_BASE"].rstrip("/")
MODEL = os.environ["SEEDREAM_MODEL"]
print("input size:", src.size, flush=True)

for box in [(256, 256), (800, 800)]:
    im = src.resize(box, Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    payload = {"model": MODEL,
               "prompt": "把纯白背景替换为柔和的米色摄影棚台面场景，商品保持原样。",
               "image": "data:image/png;base64," + b64,
               "response_format": "url", "size": "1K", "watermark": False}
    body = json.dumps(payload).encode()
    t0 = time.time()
    try:
        req = urllib.request.Request(BASE + "/images/generations", data=body,
                                     headers={"Authorization": "Bearer " + KEY,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=150) as r:
            d = json.loads(r.read().decode())
        print(box, "-> HTTP 200 in %.1fs, images=%d, body=%.0fKB"
              % (time.time() - t0, len(d.get("data", [])), len(body) / 1024), flush=True)
    except Exception as e:
        print(box, "-> FAIL in %.1fs (body=%.0fKB):" % (time.time() - t0, len(body) / 1024),
              repr(e)[:160], flush=True)
