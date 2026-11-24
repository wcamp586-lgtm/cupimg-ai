#!/usr/bin/env python3
"""分块并发下载 rembg 的 isnet-general-use 权重（GitHub 直连被网络策略挡住时的兜底）。

安全：下载源可以是第三方 GitHub 加速镜像，但**必须**通过 rembg 官方内置的
MD5 fc16ebd8b0c10d971d3513d564d01e29 校验，校验不过直接删除，绝不加载。
"""
import hashlib
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

URL = ("https://gh-proxy.com/https://github.com/danielgatis/rembg/"
       "releases/download/v0.0.0/isnet-general-use.onnx")
FALLBACKS = [
    "https://ghproxy.net/https://github.com/danielgatis/rembg/"
    "releases/download/v0.0.0/isnet-general-use.onnx",
]
TOTAL = 178_648_008
EXPECT_MD5 = "fc16ebd8b0c10d971d3513d564d01e29"
CHUNKS = 16
DEST = Path(os.path.expanduser("~/.u2net/isnet-general-use.onnx"))
TMP = DEST.with_suffix(".onnx.part")


def fetch_range(idx, start, end, url):
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}",
                                               "User-Agent": "Mozilla/5.0"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            if len(data) != end - start + 1:
                raise ValueError(f"chunk {idx} length {len(data)} != {end-start+1}")
            return idx, data
        except Exception as e:
            last = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"chunk {idx} failed: {last}")


def main():
    DEST.parent.mkdir(parents=True, exist_ok=True)
    if DEST.exists():
        h = hashlib.md5(DEST.read_bytes()).hexdigest()
        if h == EXPECT_MD5:
            print(f"ALREADY_OK | {DEST} | md5={h}")
            return 0
        print("EXISTING_FILE_MD5_MISMATCH, re-downloading")
        DEST.unlink()

    size = (TOTAL + CHUNKS - 1) // CHUNKS
    ranges = [(i, i * size, min((i + 1) * size - 1, TOTAL - 1)) for i in range(CHUNKS)]
    parts = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=CHUNKS) as ex:
        futs = {ex.submit(fetch_range, i, s, e, URL): (i, s, e) for i, s, e in ranges}
        for f in as_completed(futs):
            i, s, e = futs[f]
            try:
                idx, data = f.result()
                parts[idx] = data
                print(f"  chunk {idx+1:02d}/{CHUNKS} OK ({len(data)//1024} KB)", flush=True)
            except Exception as err:
                # 单块失败：换备用镜像重试一次
                print(f"  chunk {i+1:02d} retry via fallback: {str(err)[:100]}", flush=True)
                idx, data = fetch_range(i, s, e, FALLBACKS[0])
                parts[idx] = data
                print(f"  chunk {idx+1:02d}/{CHUNKS} OK via fallback", flush=True)

    if len(parts) != CHUNKS:
        print("DOWNLOAD_INCOMPLETE")
        return 1
    with TMP.open("wb") as f:
        for i in range(CHUNKS):
            f.write(parts[i])
    h = hashlib.md5(TMP.read_bytes()).hexdigest()
    print(f"MD5={h} | EXPECTED={EXPECT_MD5} | elapsed={time.time()-t0:.1f}s")
    if h != EXPECT_MD5:
        TMP.unlink(missing_ok=True)
        print("CHECKSUM_FAILED | 文件已删除，未加载")
        return 1
    TMP.replace(DEST)
    print(f"MODEL_READY | {DEST} | {DEST.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
