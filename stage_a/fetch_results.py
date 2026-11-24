"""把服务器容器内的 Stage A 产物回传本机并生成人眼验收材料。

背景：首尔服务器 SSH/scp 单连接下行约 17 KB/s，并行 6-10 路约 54-90 KB/s，
所以产物按 case 打成小 zip 后并行拉取，避免跨境单流把 20 MB 拖成 20 分钟。

用法（工作区根目录）：
    python stage_a/fetch_results.py

产物落在本机 stage_a/results/：
    scorecard.md / scorecard.json / review_sheet.csv
    compare/<case>.png            10 张三栏对比图
    cases/<case>/                 每个 case 的 run.log / iou.txt
    products/<case>/final/*      成品主图/场景图/详情图/SVG（人眼看细节用）
    contact.jpg                   10 张对比图总览拼图
"""
import base64
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
KEY = ROOT / "m0" / ".secrets" / "lighthouse_ed25519"
HOST = "ubuntu@101.33.74.41"
SSH_BASE = ["ssh", "-i", str(KEY), "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=25", HOST]
SCP_BASE = ["scp", "-i", str(KEY), "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=25"]
DEST = HERE / "results"
CONTAINER = "deploy-api-1"

# 在服务器宿主机执行：把容器内产物 copy 出来，按 case 打包成小 zip。
REMOTE_PACK = r'''
import zipfile
from pathlib import Path

out = Path("/tmp/sa_out")
cases = Path("/tmp/sa_cases")
pkgs = Path("/tmp/sa_pkgs")
pkgs.mkdir(exist_ok=True)
for p in pkgs.glob("*.zip"):
    p.unlink()

# 全局报告（scorecard / review_sheet / 各 case 的 run.log、iou.txt）
with zipfile.ZipFile(pkgs / "_reports.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(out.rglob("*")):
        if p.is_file() and "compare" not in p.parts:
            z.write(p, "out/" + str(p.relative_to(out)).replace("\\", "/"))

made = []
for cdir in sorted([d for d in cases.iterdir() if d.is_dir()]):
    cid = cdir.name
    with zipfile.ZipFile(pkgs / (cid + ".zip"), "w", zipfile.ZIP_DEFLATED) as z:
        cmp_png = out / "compare" / (cid + ".png")
        if cmp_png.is_file():
            z.write(cmp_png, "compare/" + cmp_png.name)
        cdir_out = out / cid
        if cdir_out.is_dir():
            for f in sorted(cdir_out.glob("*")):
                if f.is_file():
                    z.write(f, "case/" + f.name)
        # 产物在 <case>/<sku>/ 下再分 final / evidence / editable，
        # 去掉 sku 这一层，让本地路径固定为 products/<case>/final/...
        sku_dirs = [d for d in cdir.iterdir() if d.is_dir()]
        base = sku_dirs[0] if sku_dirs else cdir
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(base)
            keep = (rel.parts[0] in ("final", "evidence", "editable")
                    or rel.name in ("delivery.json", "design.json"))
            if keep:
                z.write(p, "product/" + str(rel).replace("\\", "/"))
    made.append(cid + ".zip")

for p in sorted(pkgs.glob("*.zip")):
    p.chmod(0o644)
    print("PKG %s %d" % (p.name, p.stat().st_size))
print("PKG_COUNT %d" % len(list(pkgs.glob("*.zip"))))
'''


def ssh(cmd, timeout=300):
    r = subprocess.run(SSH_BASE + [cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("SSH 失败: %s\n%s" % (r.stdout[-600:], r.stderr[-600:]))
    return r.stdout


def main():
    if not KEY.is_file():
        raise SystemExit("缺少 SSH 私钥：%s" % KEY)
    DEST.mkdir(parents=True, exist_ok=True)

    print("[1/5] 从容器导出产物到宿主机 ...")
    print(ssh(
        "sudo rm -rf /tmp/sa_out /tmp/sa_cases /tmp/sa_pkgs /tmp/sa_pack.py && "
        "sudo docker cp %s:/app/stage_a/out /tmp/sa_out && "
        "sudo docker cp %s:/app/m0/out/stage_a /tmp/sa_cases && "
        "echo EXPORT_OK" % (CONTAINER, CONTAINER)).strip())

    print("[2/5] 按 case 打包 ...")
    b64 = base64.b64encode(REMOTE_PACK.encode("utf-8")).decode("ascii")
    ssh("echo %s | base64 -d | sudo tee /tmp/sa_pack.py >/dev/null && "
        "sudo python3 /tmp/sa_pack.py" % b64)
    listing = ssh("sudo ls -1 /tmp/sa_pkgs/*.zip | xargs -n1 basename").split()
    print("    包数 =", len(listing), "|", " ".join(listing[:4]), "...")

    print("[3/5] 并行回传 ...")
    t0 = time.time()

    def one(name):
        dst = DEST / name
        r = subprocess.run(SCP_BASE + ["%s:/tmp/sa_pkgs/%s" % (HOST, name), str(dst)],
                           capture_output=True, text=True)
        return name, r.returncode, dst.stat().st_size if dst.exists() else 0

    with ThreadPoolExecutor(max_workers=min(10, len(listing))) as ex:
        res = list(ex.map(one, listing))
    total = sum(x[2] for x in res)
    bad = [x[0] for x in res if x[1] != 0 or x[2] == 0]
    print("    回传 %d 个包 / %.2f MB / %.1fs / %.0f KB%s" %
          (len(res), total / 1048576, time.time() - t0,
           total / 1024 / max(time.time() - t0, 0.1), "/s"))
    if bad:
        raise SystemExit("回传失败: %s" % bad)

    print("[4/5] 解压到 stage_a/results/ ...")
    names = []
    for name in listing:
        z = zipfile.ZipFile(DEST / name)
        if z.testzip() is not None:
            raise SystemExit("ZIP CRC 损坏: %s" % name)
        if name == "_reports.zip":
            for m in z.namelist():
                rel = m[len("out/"):] if m.startswith("out/") else m
                p = DEST / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(z.read(m))
            continue
        cid = name[:-4]
        names.append(cid)
        for m in z.namelist():
            if m.startswith("compare/"):
                p = DEST / m
            elif m.startswith("case/"):
                p = DEST / "cases" / cid / m[len("case/"):]
            else:
                p = DEST / "products" / cid / m[len("product/"):]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(z.read(m))
    print("    case 数 =", len(names))
    # 临时包清理失败不影响交付（部分环境把 unlink 接管成回收站操作会失败）
    for name in listing:
        try:
            (DEST / name).unlink()
        except OSError:
            pass

    fix_report_paths()
    print("[5/5] 生成总览拼图 ...")
    make_contact(names)
    print("DONE:", DEST)


def fix_report_paths():
    """scorecard.md 里的路径是脚本运行时（服务器容器）的路径，改成本机回传后的路径。"""
    p = DEST / "scorecard.md"
    if not p.is_file():
        return
    s = p.read_text(encoding="utf-8")
    s = s.replace("stage_a/out/<case>/run.log", "stage_a/results/cases/<case>/run.log")
    s = s.replace("stage_a/out/", "stage_a/results/")
    p.write_text(s, encoding="utf-8")


def _cn_font(size):
    """PIL 默认字体不含中文，总览图的类别/关注点会变成方块。"""
    from PIL import ImageFont
    cands = [ROOT / "assets" / "fonts" / "MiSans-Regular.otf",
             Path("C:/Windows/Fonts/msyh.ttc"),
             Path("C:/Windows/Fonts/simhei.ttf")]
    for f in cands:
        if f.is_file():
            try:
                return ImageFont.truetype(str(f), size)
            except Exception:
                pass
    return ImageFont.load_default()


def make_contact(names):
    from PIL import Image, ImageDraw

    cfg = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    focus = {c["id"]: (c["category"], c.get("focus", "")) for c in cfg["cases"]}
    W, H, COLS = 620, 244, 2
    f_main, f_sub = _cn_font(15), _cn_font(12)
    rows = (len(names) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * W, rows * H), "#f4f4f4")
    d = ImageDraw.Draw(sheet)
    for i, cid in enumerate(names):
        p = DEST / "compare" / (cid + ".png")
        x, y = (i % COLS) * W, (i // COLS) * H
        if p.is_file():
            im = Image.open(p).convert("RGB")
            im.thumbnail((W - 8, H - 44))
            sheet.paste(im, (x + (W - im.width) // 2, y + 2))
        iou = "-"
        ip = DEST / "cases" / cid / "iou.txt"
        if ip.is_file():
            iou = ip.read_text(encoding="utf-8").strip()[:6]
        cat = focus.get(cid, ("", ""))[0]
        d.text((x + 8, y + H - 36), "%s  [%s]  IoU=%s" % (cid, cat, iou),
               fill="#222", font=f_main)
        d.text((x + 8, y + H - 17), focus.get(cid, ("", ""))[1][:44],
               fill="#666", font=f_sub)
    out = DEST / "contact.jpg"
    sheet.save(out, quality=90)
    print("    contact.jpg", sheet.size, out.stat().st_size, "B")


if __name__ == "__main__":
    main()
