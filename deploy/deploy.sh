#!/usr/bin/env bash
# 在服务器 /opt/cupimg/deploy 下执行：构建并启动，最后做健康检查。
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env.production ] || { echo "缺少 .env.production（含 API Key 与访问口令）"; exit 1; }
[ -n "${DOMAIN:-}" ] || { echo "请先 export DOMAIN=子域.主域"; exit 1; }
export DOMAIN

# ubuntu 用户可能尚未加入 docker 组（新 SSH 会话才生效），自动选择是否需要 sudo
if docker ps >/dev/null 2>&1; then DC=(docker compose); else DC=(sudo docker compose); fi
echo "== 使用命令: ${DC[*]} =="

echo "== 构建镜像（首次约 5-10 分钟）=="
"${DC[@]}" build

echo "== 启动 =="
"${DC[@]}" up -d

echo "== 容器状态 =="
"${DC[@]}" ps

echo "== 等待 API 就绪 =="
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1:8000/healthz && echo

echo "== HTTPS 探测（证书首次申请需等 DNS 生效）=="
sleep 8
curl -sS -o /dev/null -w "https_status=%{http_code}\n" "https://${DOMAIN}/healthz" || true
echo "DEPLOY_DONE"
