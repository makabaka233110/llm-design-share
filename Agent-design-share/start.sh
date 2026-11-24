#!/bin/bash
# 面壁 Mianbi — 一键启动（macOS / Linux，需要 Python 3.12+ 或 uv）
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "已创建 .env，请填入 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 后重新运行 bash start.sh"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "[1/2] 安装依赖（首次运行需联网，会下载约 600MB 的 bge-m3 模型）..."
  if command -v uv >/dev/null; then
    uv venv -q -p 3.12 .venv && uv pip install -q -p .venv/bin/python -e ".[speech]"
  else
    PY=$(command -v python3.13 || command -v python3.12) || { echo "需要 Python 3.12+ 或 uv"; exit 1; }
    "$PY" -m venv .venv && .venv/bin/pip install -q -e ".[speech]"
  fi
fi

echo "[2/2] 启动：http://127.0.0.1:8000   API 文档：http://127.0.0.1:8000/docs"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
