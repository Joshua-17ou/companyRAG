#!/bin/bash

# Docker容器启动脚本 - 同时启动后端和前端

echo "🚀 RAG系统启动脚本"
echo "=================================="

# 启动后端服务（不使用--reload，在后台）
echo "🚀 启动FastAPI后端服务（端口 8000）..."
cd /app
python scripts/start_backend.py &

BACKEND_PID=$!
echo "📌 后端进程ID: $BACKEND_PID"

# 等待后端启动并就绪（检查健康检查端点）
echo "⏳ 等待后端服务就绪..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ 后端服务已就绪"
        break
    fi
    attempt=$((attempt + 1))
    echo "  尝试 $attempt/$max_attempts..."
    sleep 1
done

if [ $attempt -eq $max_attempts ]; then
    echo "⚠️ 后端服务启动超时，但继续启动前端..."
    echo "检查上面的日志了解后端启动错误"
fi

# 启动前端服务（前台运行）
echo ""
echo "🚀 启动Streamlit前端服务（端口 8501）..."
streamlit run /app/app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --logger.level=info &

FRONTEND_PID=$!
echo "📌 前端进程ID: $FRONTEND_PID"

echo ""
echo "=================================="
echo "✅ RAG系统已启动"
echo ""
echo "📱 前端访问: http://localhost:8501"
echo "🔌 后端API: http://localhost:8000"
echo "=================================="
echo ""
echo "后台运行的服务："
ps aux | grep -E "uvicorn|streamlit" | grep -v grep
echo ""

# 清理退出处理
cleanup() {
    echo ""
    echo "⏹️  正在关闭服务..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGTERM SIGINT

# 持续监控进程
while true; do
    if ! kill -0 $BACKEND_PID 2>/dev/null; then
        echo "❌ 后端进程已退出，检查上面的日志"
        break
    fi
    if ! kill -0 $FRONTEND_PID 2>/dev/null; then
        echo "❌ 前端进程已退出，检查上面的日志"
        break
    fi
    sleep 5
done
