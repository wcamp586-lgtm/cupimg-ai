FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    U2NET_HOME=/app/assets/models \
    REMBG_MODEL=u2netp

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY deploy/requirements.txt /tmp/requirements.txt
RUN python -m pip install --timeout 60 --retries 3 -r /tmp/requirements.txt

# 全部代码与数据（.dockerignore 会排除 .env / .secrets / out / 调试产物）
COPY m0 /app/m0
COPY webapp /app/webapp
COPY assets /app/assets

# 白名单可商用中文字体：Linux 下 compose.find_font() 会扫 /usr/share/fonts
COPY assets/fonts/MiSans-Regular.otf /usr/share/fonts/MiSans-Regular.otf

RUN mkdir -p /app/data /app/m0/out \
 && python -c "from PIL import Image; import rembg, onnxruntime, fastapi, uvicorn; print('deps ok')"

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
