#!/usr/bin/env python3
"""只读盘点 7 个美工交付 RAR：图位、尺寸、格式、单图大小，判断有无统一规则。

不解压落盘、不改动原目录；用 7z e -so 读文件头量尺寸。
输出 stage_a/results/package_specs.json 供后续配置参考。
"""
import io
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

SEVEN = r"C:\Program Files\7-Zip\7z.exe"
SRC = Path(r"D:\xwechat_files\wxid_dprlbcp5gfdr22_b197\msg\attach"
           r"\040c2811eb8255a3c915a4bcd93c90f7\2026-11\Rec"
           r"\ec94b541ff8a92ed\F")
OUT = Path(__file__).resolve().parents[0] / "results" / "package_specs.json"
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def list_archive(rar):
    p = subprocess.run([SEVEN, "l", "-slt", str(rar)], capture_output=True)
    txt = p.stdout.decode("gbk", errors="replace")
    # 7-Zip -slt 的记录之间只用空行分隔，不是 "----------"；以 Path = 作为新记录起点
    entries, cur = [], {}
    for line in txt.splitlines():
        if line.startswith("Path = "):
            if cur.get("Path"):
                entries.append(cur)
            cur = {"Path": line[len("Path = "):].strip()}
        elif " = " in line:
            k, v = line.split(" = ", 1)
            cur[k.strip()] = v.strip()
    if cur.get("Path"):
        entries.append(cur)
    return [e for e in entries
            if e.get("Folder") == "-" and e.get("Size")
            and Path(e["Path"]).suffix.lower() in IMG_EXT]


def parse_dims(data):
    """纯标准库读图片头：PNG IHDR / JPEG SOF / GIF，不依赖 Pillow。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return ("(%d, %d)" % (int.from_bytes(data[16:20], "big"),
                              int.from_bytes(data[20:24], "big")), "PNG")
    if data[:2] == b"\xff\xd8":
        i = 2
        sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
               0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            m = data[i + 1]
            if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            seg = int.from_bytes(data[i + 2:i + 4], "big")
            if m in sof:
                h = int.from_bytes(data[i + 5:i + 7], "big")
                w = int.from_bytes(data[i + 7:i + 9], "big")
                return ("(%d, %d)" % (w, h), "JPEG")
            if seg < 2:
                break
            i += 2 + seg
        return (None, None)
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return ("(%d, %d)" % (int.from_bytes(data[6:8], "little"),
                              int.from_bytes(data[8:10], "little")), "GIF")
    return (None, None)


def read_head(rar, path, n=262144):
    p = subprocess.Popen([SEVEN, "e", "-so", str(rar), path],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    data = p.stdout.read(n)
    p.stdout.close()
    try:
        p.kill()
        p.wait(timeout=3)
    except Exception:
        pass
    if not data:
        return (None, None)
    d = parse_dims(data)
    if d[0]:
        return d
    # 少数 JPEG 的 SOF 在更后面，回退完整读取
    q = subprocess.run([SEVEN, "e", "-so", str(rar), path], capture_output=True)
    return parse_dims(q.stdout)


def group_of(path):
    parts = path.split("\\")
    rest = parts[1:]
    if not rest:
        return "顶层散图"
    d = rest[0]
    low = d.lower()
    if low == "images":
        return "images(详情切片)"
    if low == "sku":
        return "sku"
    if "主图" in d:
        return "主图"
    if "白底" in d or "透明" in d:
        return d
    return d


def main():
    rars = sorted(SRC.glob("*/*.rar"))
    print("找到 %d 个 RAR" % len(rars), flush=True)
    report = {"source": str(SRC), "packages": [], "cross_package": {}}
    all_main_dims, all_slice_dims, all_main_counts, all_slice_counts = [], [], [], []
    for rar in rars:
        entries = list_archive(rar)
        groups = defaultdict(list)
        for e in entries:
            groups[group_of(e["Path"])].append(e)
        pkg = {"name": rar.name, "size_mb": round(rar.stat().st_size / 1048576, 1),
               "image_files": len(entries), "groups": {}}
        print("\n=== %s (%.1f MB, %d 张图) ===" %
              (rar.name, pkg["size_mb"], len(entries)), flush=True)
        for g, items in sorted(groups.items()):
            dims = Counter()
            sizes = []
            detail = []
            for e in items:
                size = int(e["Size"])
                sizes.append(size)
                size_str, fmt = read_head(rar, e["Path"])
                dims[size_str] += 1
                detail.append({"file": e["Path"].split("\\")[-1],
                               "bytes": size, "dims": size_str, "format": fmt})
            pkg["groups"][g] = {
                "count": len(items),
                "dims": dict(dims),
                "bytes_min": min(sizes), "bytes_max": max(sizes),
                "bytes_avg": round(sum(sizes) / len(sizes)),
                "files": detail,
            }
            print("  %-18s %3d 张 | 尺寸 %s | %d–%d KB" %
                  (g, len(items), dict(dims), min(sizes) // 1024,
                   max(sizes) // 1024), flush=True)
            if g == "主图":
                all_main_counts.append(len(items))
                all_main_dims += [d for d, c in dims.items() for _ in range(c)]
            if g.startswith("images"):
                all_slice_counts.append(len(items))
                all_slice_dims += [d for d, c in dims.items() for _ in range(c)]
        report["packages"].append(pkg)
    report["cross_package"] = {
        "main_counts": all_main_counts,
        "main_dims": dict(Counter(all_main_dims)),
        "slice_counts": all_slice_counts,
        "slice_dims_top": dict(Counter(all_slice_dims).most_common(20)),
        "distinct_slice_dims": len(set(all_slice_dims)),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== 跨包汇总 ===", flush=True)
    print(json.dumps(report["cross_package"], ensure_ascii=False, indent=2), flush=True)
    print("\nSAVED", OUT, flush=True)


if __name__ == "__main__":
    sys.exit(main())
