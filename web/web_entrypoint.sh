#!/bin/sh
set -e

# 默认环境变量
WEB_PORT=${WEB_PORT:-5000}
CONFIG_CONSOLE_PORT=${CONFIG_CONSOLE_PORT:-5002}
WORKERS=${GUNICORN_WORKERS:-1}
THREADS=${GUNICORN_THREADS:-4}

echo "[Web] Starting services..."

# 1. 启动配置控制台 (Config Console) - HTTP :5002
# 仅当启用时启动
if [ "${CONFIG_CONSOLE_ENABLED:-1}" != "0" ]; then
    echo "[Web] Starting Config Console on port $CONFIG_CONSOLE_PORT..."
    # 使用 exec 在后台运行，确保不阻塞
    gunicorn app:config_app \
        --bind 0.0.0.0:$CONFIG_CONSOLE_PORT \
        --workers 1 \
        --threads $THREADS \
        --access-logfile - \
        --error-logfile - \
        &
fi

# 2. 启动主应用 (Main Dashboard) - HTTPS :5000
# 检查 SSL 配置
SSL_ARGS=""
if [ "${WEB_SSL_ENABLED:-0}" != "0" ]; then
    if [ -f "$WEB_SSL_CERT" ] && [ -f "$WEB_SSL_KEY" ]; then
        echo "[Web] SSL Enabled. Cert: $WEB_SSL_CERT"
        SSL_ARGS="--certfile $WEB_SSL_CERT --keyfile $WEB_SSL_KEY"
    else
        echo "[Web] SSL Enabled but certificates not found at $WEB_SSL_CERT / $WEB_SSL_KEY. Falling back to HTTP."
    fi
else
    echo "[Web] SSL Disabled. Running in HTTP mode."
fi

echo "[Web] Starting Main Dashboard on port $WEB_PORT..."
# 主进程前台运行
exec gunicorn app:app \
    --bind 0.0.0.0:$WEB_PORT \
    --workers $WORKERS \
    --threads $THREADS \
    $SSL_ARGS \
    --access-logfile - \
    --error-logfile - \
    --capture-output
