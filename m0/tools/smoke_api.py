#!/usr/bin/env python3
"""最小真实调用验证：确认 .env 里的 Key 与业务空间域名可用。

只发一条短文本请求，消耗可忽略（且在 100 万 Token 免费额度内）。
绝不打印密钥内容。
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path):
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


env = load_env(ROOT / ".env")
key = (env.get("DASHSCOPE_API_KEY") or "").strip()
base = (env.get("DASHSCOPE_BASE") or "").strip().rstrip("/")
model = (env.get("TEXT_MODEL") or "qwen3.7-plus").strip()

if not key or not base:
    print("FAIL: .env 缺少 DASHSCOPE_API_KEY / DASHSCOPE_BASE")
    raise SystemExit(1)

url = base + "/chat/completions"
models = [("TEXT", model), ("VL", (env.get("VL_MODEL") or "qwen3-vl-plus").strip())]
results = []
for tag, m in models:
    payload = {
        "model": m,
        "messages": [{"role": "user", "content": "只回复两个字：可用"}],
        "max_tokens": 16,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            print(f"{tag}: HTTP=200 | MODEL={data.get('model', m)} | REPLY={str(text).replace(chr(10), ' ')[:40]} | TOKENS={usage.get('total_tokens')}")
            results.append(True)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:220]
        print(f"{tag}: HTTP={e.code} | {body}")
        results.append(False)
    except Exception as e:
        print(f"{tag}: ERROR={repr(e)[:200]}")
        results.append(False)

print("SMOKE_RESULT=" + ("PASS" if all(results) else "PARTIAL_OR_FAIL"))
