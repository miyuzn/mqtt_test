#!/bin/sh
# backend_entrypoint.sh
# 这是一个组合启动脚本，用于在单个容器中运行 Parser 和 Bridge 服务

echo "[Backend] Starting Raw Parser Service..."
python /server/raw_parser_service.py &

echo "[Backend] Starting Bridge Service..."
python /server/bridge.py &

# 等待所有后台进程
# 如果任何一个进程退出，容器将继续运行另一个（除非添加复杂的进程监控逻辑）
# 在简单的 Docker 场景下，wait 会等待所有后台任务
wait
