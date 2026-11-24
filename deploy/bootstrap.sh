#!/usr/bin/env bash
# 在首尔轻量机（Ubuntu 24.04）上首次执行：安装 Docker、放行 80/443、准备目录。
set -euo pipefail

echo "== 1/4 系统更新与 Docker 安装 =="
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
sudo usermod -aG docker "${USER:-ubuntu}" || true
sudo systemctl enable --now docker

echo "== 2/4 本机防火墙（ufw）放行 =="
if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow 80/tcp || true
  sudo ufw allow 443/tcp || true
  echo "ufw 已放行 80/443"
else
  echo "ufw 未启用，跳过（腾讯云轻量防火墙在控制台单独配置）"
fi

echo "== 3/4 目录准备 =="
sudo mkdir -p /opt/cupimg/deploy/data/out /opt/cupimg/deploy/data/jobs
sudo chown -R "${USER:-ubuntu}:${USER:-ubuntu}" /opt/cupimg || true

echo "== 4/4 Docker 可用性与资源 =="
docker --version
docker compose version
df -h / | tail -1
free -h | head -2
echo "BOOTSTRAP_OK"
