FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_ENDPOINT=https://hf-mirror.com

WORKDIR /workspace/backend

# 仅安装 PyTorch 运行所需的 libgomp1。
# trixie-updates / trixie-security 可能返回 502,但主仓库可用,
# 因此允许 update 失败后继续安装。
RUN (apt-get update -o Acquire::Retries=3 || true) \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts

RUN mkdir -p /workspace/logs /workspace/knowledge_base /workspace/config

EXPOSE 8000

# 使用 Python 标准库做健康检查,无需安装 curl
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=10)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
