#!/usr/bin/env bash
# 在「已有 nginx 占着 80/443」的服务器上，为本服务新增一条独立反代规则。
# 只新增一个 sites-enabled 文件，不修改任何现有站点配置；先 nginx -t 校验再 reload。
# 前置：api 容器已在 127.0.0.1:8000 提供 HTTP。
set -euo pipefail

CONF=/etc/nginx/sites-enabled/cupimg.aicloud.plus.conf
BACKUP=/opt/cupimg/deploy/nginx_conf_backup_$(date +%Y%m%d-%H%M%S).tar.gz

echo "== 备份现有 nginx 站点配置（可回滚）=="
sudo tar -czf "$BACKUP" -C /etc/nginx sites-enabled nginx.conf 2>/dev/null || true
echo "BACKUP=$BACKUP"

echo "== 写入本服务专用 server block（监听 80，反代回环 8000）=="
sudo tee "$CONF" >/dev/null <<'EOF'
server {
    listen 80;
    server_name cupimg.aicloud.plus;
    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 900s;
        proxy_send_timeout 900s;
    }
}
EOF

echo "== 语法校验（不通过就删除新文件并退出，绝不 reload）=="
if ! sudo nginx -t; then
  sudo rm -f "$CONF"
  echo "NGINX_CONFIG_INVALID: 已回滚新增文件"
  exit 1
fi

echo "== 平滑 reload（现有站点不受影响）=="
sudo systemctl reload nginx
echo "NGINX_PROXY_OK"
