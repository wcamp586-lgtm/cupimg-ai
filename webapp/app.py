#!/usr/bin/env python3
"""小范围邀请制 Web 端：上传定稿商品图 → 后台跑 M0 live 管线 → 预览/下载成品。

2C4G 首尔机约束下的刻意设计：
- 访问口令（签名 cookie），防止链接被转发、被爬
- 单线程队列，并发恒为 1（内存紧、免费生图额度有限）
- 每日任务上限，防止免费额度被刷光
- 只暴露 final/ 与 editable/ 下的白名单产物，绝不暴露 .env / 源码 / 密钥
"""
import hashlib
import hmac
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

ROOT = Path(__file__).resolve().parent.parent
M0 = ROOT / "m0"
DATA = Path(os.environ.get("WB_DATA_DIR", ROOT / "data"))
JOBS_DIR = DATA / "jobs"
OUT = M0 / "out"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

ACCESS_CODE = os.environ.get("ACCESS_CODE", "").strip()
if not ACCESS_CODE:
    raise RuntimeError("ACCESS_CODE 未设置：拒绝以无口令状态对外提供服务")
COOKIE_VALUE = hashlib.sha256(("wb1688:" + ACCESS_CODE).encode("utf-8")).hexdigest()
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "8"))
JOB_TIMEOUT_S = int(os.environ.get("JOB_TIMEOUT_S", "900"))
# 本地联调可设 offline，零消耗验证 Web 链路；线上固定 live
PIPELINE_MODE = os.environ.get("PIPELINE_MODE", "live")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "15"))
ASSETS = {"main_white.png": "final", "scene.png": "final",
          "detail.png": "final", "design.svg": "editable"}

app = FastAPI(title="1688 杯具 AI 作图 · 内测", docs_url=None, redoc_url=None,
              openapi_url=None)

JOBS = {}
LOCK = threading.Lock()
Q = queue.Queue()

# 容器默认 UTC；对内按北京时间口径，避免"每日 8 次"在早上 8 点前算错天
TZ_CN = timezone(timedelta(hours=8))


def now_cn():
    return datetime.now(TZ_CN)


def today_str():
    return now_cn().date().isoformat()


def stamp():
    return now_cn().strftime("%Y-%m-%d %H:%M:%S")


DAILY = {"day": today_str(), "count": 0}


def restore_state():
    """容器重启后从磁盘恢复任务表与当日限额。

    否则 restart: unless-stopped 拉起容器时 JOBS 清空，朋友之前跑过的任务
    会查不到 / 下载 404，每日限额也会归零被反复刷免费额度。
    """
    global DAILY
    restored, used, interrupted = 0, 0, 0
    today = today_str()
    for p in sorted(JOBS_DIR.glob("*/job.json")):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not j.get("id"):
            continue
        j = {k: v for k, v in j.items() if not k.startswith("_")}
        # 子进程随容器一起消失，排队/运行中的任务不可能自动续跑
        if j.get("phase") in ("queued", "running"):
            j["phase"] = "failed"
            j["error"] = "服务重启导致任务中断，请重新上传"
            interrupted += 1
            try:
                save_job(j)
            except Exception:
                pass
        JOBS[j["id"]] = j
        restored += 1
        if str(j.get("created_at", "")).startswith(today):
            used += 1
    DAILY = {"day": today, "count": used}
    print("RESTORE jobs=%d interrupted=%d day=%s used=%d" %
          (restored, interrupted, today, used), flush=True)


def log(job, line):
    with LOCK:
        job["log"].append(str(line).rstrip())
        if len(job["log"]) > 400:
            job["log"] = job["log"][-400:]
        save_job(job)


def save_job(job):
    p = JOBS_DIR / job["id"] / "job.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    safe = {k: v for k, v in job.items() if not k.startswith("_")}
    tmp.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def require_access(request):
    if not hmac.compare_digest(request.cookies.get("wb_access", ""), COOKIE_VALUE):
        raise HTTPException(status_code=401, detail="访问口令无效或已过期")


def public(job):
    return {k: job.get(k) for k in
            ("id", "phase", "step", "created_at", "sku", "delivery_state",
             "delivery_reason", "assets", "error", "log")}


def run_job(job):
    jid = job["id"]
    with LOCK:
        job["phase"] = "running"
        job["started_at"] = time.time()
        save_job(job)
    job_dir = JOBS_DIR / jid
    input_path = job_dir / "input.jpg"
    facts_path = job_dir / "facts.json"
    cmd = [sys.executable, "run.py", "--mode", PIPELINE_MODE, "--tenant", jid,
           "--input", str(input_path), "--facts", str(facts_path),
           # 主图 1 固定原图直通，不依赖 run.py 默认值，避免以后改默认影响线上口径
           "--white-source", "original",
           # 场景走 Seedream 图生图直出 + 自动形变门禁（2026-11-24 定调）
           "--scene-mode", "i2i"]
    log(job, "$ " + " ".join(cmd[1:]))
    env = os.environ.copy()
    env.setdefault("REMBG_MODEL", "u2netp")   # 已校验可商用轻量权重，生产再换 isnet
    env.setdefault("U2NET_HOME", str(ROOT / "assets" / "models"))
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(cmd, cwd=str(M0), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)

    def reader():
        for line in proc.stdout:
            log(job, line)
            if line.startswith("["):
                try:
                    job["step"] = int(line[1:3])
                except (ValueError, IndexError):
                    pass

    t = threading.Thread(target=reader, daemon=True, name="job-log-" + jid)
    t.start()
    try:
        proc.wait(timeout=JOB_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=20)
        log(job, "TIMEOUT: 超过 %d 秒，任务已终止" % JOB_TIMEOUT_S)
    except Exception as e:
        proc.kill()
        log(job, "PROCESS ERROR: " + repr(e))
    t.join(timeout=10)

    root = OUT / jid / job["sku"]
    delivery = root / "delivery.json"
    if delivery.exists():
        try:
            d = json.loads(delivery.read_text(encoding="utf-8"))
            job["delivery_state"] = d.get("delivery_state", "NEEDS_REVIEW")
            job["delivery_reason"] = d.get("delivery_reason", "")
        except Exception:
            pass
    found = []
    for name in ASSETS:
        if (root / ASSETS[name] / name).exists():
            found.append(name)
    with LOCK:
        job["assets"] = found
        job["phase"] = "done" if found and proc.returncode == 0 else "failed"
        job["finished_at"] = time.time()
        if job["phase"] == "failed" and not job.get("error"):
            job["error"] = "流水线未产出成品，请查看日志"
        save_job(job)
    log(job, "JOB %s | delivery=%s | assets=%s" %
        (job["phase"].upper(), job.get("delivery_state"), ",".join(found) or "none"))


def worker():
    while True:
        jid = Q.get()
        job = JOBS.get(jid)
        try:
            if job and job["phase"] == "queued":
                run_job(job)
        except Exception as e:
            if job:
                with LOCK:
                    job["phase"] = "failed"
                    job["error"] = repr(e)
                    save_job(job)
        finally:
            Q.task_done()


restore_state()
threading.Thread(target=worker, daemon=True, name="pipeline-worker").start()


@app.get("/healthz")
def healthz():
    return {"ok": True, "queue": Q.qsize(), "day": DAILY["day"], "used": DAILY["count"]}


@app.post("/api/login")
async def login(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求格式错误")
    if not hmac.compare_digest(str(body.get("code", "")), ACCESS_CODE):
        raise HTTPException(status_code=401, detail="口令不对")
    r = JSONResponse({"ok": True})
    r.set_cookie("wb_access", COOKIE_VALUE, httponly=True, samesite="lax",
                 max_age=7 * 24 * 3600, path="/")
    return r


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "webapp" / "index.html").read_text(encoding="utf-8")


@app.post("/api/jobs")
async def create_job(request: Request, image: UploadFile = File(...),
                     sku: str = Form(...), name: str = Form(...),
                     material: str = Form(...), capacity_ml: str = Form(...),
                     color: str = Form(...), dimensions_mm: str = Form(""),
                     logo_text: str = Form(""), brand: str = Form(""),
                     shape_note: str = Form(""), has_handle: str = Form("false")):
    require_access(request)
    global DAILY
    with LOCK:
        if DAILY["day"] != today_str():
            DAILY = {"day": today_str(), "count": 0}
        if DAILY["count"] >= DAILY_LIMIT:
            raise HTTPException(status_code=429,
                                detail="今日体验额度已用完（每日 %d 次），明天再来" % DAILY_LIMIT)
        DAILY["count"] += 1

    sku = "".join(c for c in sku.strip() if c.isalnum() or c in "-_")[:40]
    if not sku:
        raise HTTPException(status_code=400, detail="SKU 不能为空")
    try:
        cap = int(capacity_ml)
        if cap <= 0 or cap > 100000:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="容量必须是正数（ml）")

    raw = await image.read()
    if not raw or len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片为空或超过 %d MB" % MAX_UPLOAD_MB)
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw))
        im.verify()
        im = Image.open(io.BytesIO(raw))
        # 透明底定稿图：alpha 合成到白底再转 RGB（convert("RGB") 会直接丢 alpha，
        # 透明区变成杂色底，原图直通的主图合规必挂——2026-11-24 cap_01 实测踩坑）
        if im.mode in ("RGBA", "LA", "PA") or (
                im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            im = flat
        else:
            im = im.convert("RGB")   # 顺带剥离 EXIF
    except Exception:
        raise HTTPException(status_code=400, detail="不是有效图片文件")

    jid = now_cn().strftime("%Y%m%d-%H%M%S") + "-" + hashlib.sha1(
        (sku + str(time.time())).encode()).hexdigest()[:6]
    job_dir = JOBS_DIR / jid
    job_dir.mkdir(parents=True, exist_ok=True)
    im.save(job_dir / "input.jpg", quality=94)
    facts = {"sku": sku, "name": name.strip(), "material": material.strip(),
             "capacity_ml": cap, "color": color.strip(),
             "dimensions_mm": dimensions_mm.strip(), "logo_text": logo_text.strip(),
             "brand": brand.strip(), "shape_note": shape_note.strip(),
             "has_handle": has_handle.lower() in ("true", "1", "yes", "on"),
             "certifications": []}
    (job_dir / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    job = {"id": jid, "phase": "queued", "step": 0, "sku": sku,
           "created_at": stamp(),
           "delivery_state": "", "delivery_reason": "", "assets": [],
           "error": "", "log": ["任务已排队，前面还有 %d 个任务" % Q.qsize()]}
    with LOCK:
        JOBS[jid] = job
        save_job(job)
    Q.put(jid)
    return {"id": jid, "queue_ahead": Q.qsize()}


@app.get("/api/jobs/{jid}")
def get_job(jid: str, request: Request):
    require_access(request)
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return public(job)


@app.get("/api/jobs/{jid}/asset/{name}")
def get_asset(jid: str, name: str, request: Request):
    require_access(request)
    job = JOBS.get(jid)
    if not job or name not in ASSETS:
        raise HTTPException(status_code=404, detail="文件不存在")
    p = (OUT / jid / job["sku"] / ASSETS[name] / name).resolve()
    root = (OUT / jid).resolve()
    if root not in p.parents or not p.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    media = "image/svg+xml" if name.endswith(".svg") else "image/png"
    return FileResponse(p, media_type=media, filename=name)


@app.get("/api/jobs/{jid}/download")
def download(jid: str, request: Request):
    require_access(request)
    job = JOBS.get(jid)
    if not job or not job.get("assets"):
        raise HTTPException(status_code=404, detail="暂无成品")
    root = OUT / jid / job["sku"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in job["assets"]:
            p = root / ASSETS[name] / name
            if p.exists():
                z.write(p, (ASSETS[name] + "/" + name))
        for rel in ("delivery.json", "evidence/compliance_report.json",
                    "evidence/cost.json", "evidence/ai_disclosure.json"):
            p = root / rel
            if p.exists():
                z.write(p, rel)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition":
                                      'attachment; filename="%s.zip"' % job["sku"]})
