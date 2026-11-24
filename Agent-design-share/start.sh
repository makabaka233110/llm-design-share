#!/bin/bash
# 面壁 AI 面试修炼系统 - 一键启动
set -e
cd "$(dirname "$0")"

echo "=== 面壁 AI 面试修炼系统 ==="

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "已创建 .env。按模型服务的配置填入 LLM_API_KEY 后重启，即可使用 AI 功能。"
fi

if [ ! -d "venv" ]; then
    echo "[1/3] 创建虚拟环境..."
    python3 -m venv venv
fi
source venv/bin/activate

echo "[1/3] 安装依赖..."
pip install -q fastapi uvicorn[standard] python-multipart pydantic python-dotenv "memsearch[onnx]" openai faster-whisper 2>/dev/null
pip install -q funasr modelscope 2>/dev/null || true

echo "[2/3] 启动服务..."
echo ""
echo "  浏览器:  http://localhost:8000"
echo "  API文档: http://localhost:8000/docs"
echo "  架构图:  http://localhost:8000/static/architecture.html"
echo ""
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
