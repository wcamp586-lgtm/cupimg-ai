#!/usr/bin/env python3
"""把上线所需文件打成一个 tar.gz（不含本地密钥、产物、探测脚本、文档）。

用法：python deploy/make_bundle.py  →  工作区根目录 cupimg_bundle.tar.gz
服务器解压：tar -xzf cupimg_bundle.tar.gz -C /opt/cupimg
"""
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cupimg_bundle.tar.gz"

EXPLICIT = [
    "m0/run.py", "m0/requirements.txt", "m0/.gitignore",
    "webapp/app.py", "webapp/index.html",
    "assets/fonts/MiSans-Regular.otf", "assets/models/u2netp.onnx",
    "deploy/Dockerfile", "deploy/requirements.txt", "deploy/docker-compose.yml",
    "deploy/Caddyfile", "deploy/bootstrap.sh", "deploy/deploy.sh",
    "deploy/.env.production", ".dockerignore",
]
DIRS = ["m0/pipeline", "m0/vendor", "m0/data"]

files = []
for rel in EXPLICIT:
    p = ROOT / rel
    if p.is_file():
        files.append(p)
    else:
        print("WARN missing:", rel)
for d in DIRS:
    for p in (ROOT / d).rglob("*"):
        if p.is_file() and "__pycache__" not in str(p) and not p.name.endswith(".pyc"):
            files.append(p)

with tarfile.open(OUT, "w:gz") as t:
    for p in sorted(set(files)):
        arc = p.relative_to(ROOT).as_posix()
        t.add(p, arcname=arc)
        print("  +", arc, p.stat().st_size)
print("BUNDLE:", OUT, "size:", OUT.stat().st_size, "bytes | files:", len(set(files)))
