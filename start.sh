#!/bin/bash
# WaLiAPI-Python 启动脚本
# 用法: ./start.sh

set -e

cd "$(dirname "$0")"

echo "=== WaLiAPI-Python 启动 ==="

# 检查依赖
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "正在安装依赖..."
    pip3 install -r requirements.txt
fi

echo "启动服务: http://localhost:9900"
echo "管理后台: http://localhost:9900"
echo "健康检查: http://localhost:9900/health"
echo ""

python3 -m uvicorn app.main:app --host 0.0.0.0 --port 9900
