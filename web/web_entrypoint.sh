#!/bin/sh

set -e



# 榛樿鐜鍙橀噺

WEB_PORT=${WEB_PORT:-5000}

CONFIG_CONSOLE_PORT=${CONFIG_CONSOLE_PORT:-5002}

WORKERS=${GUNICORN_WORKERS:-1}

THREADS=${GUNICORN_THREADS:-4}



echo "[Web] Starting services..."



# 1. 鍚姩閰嶇疆鎺у埗鍙?(Config Console) - HTTP :5002

# 浠呭綋鍚敤鏃跺惎鍔?if [ "${CONFIG_CONSOLE_ENABLED:-1}" != "0" ]; then

    echo "[Web] Starting Config Console on port $CONFIG_CONSOLE_PORT..."

    # 浣跨敤 exec 鍦ㄥ悗鍙拌繍琛岋紝纭繚涓嶉樆濉?    gunicorn app:config_app \

        --bind 0.0.0.0:$CONFIG_CONSOLE_PORT \

        --workers 1 \

        --threads $THREADS \

        --access-logfile - \

        --error-logfile - \

        &

fi



# 2. 鍚姩涓诲簲鐢?(Main Dashboard) - HTTPS :5000

# 妫€鏌?SSL 閰嶇疆

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

# 涓昏繘绋嬪墠鍙拌繍琛?exec gunicorn app:app \

    --bind 0.0.0.0:$WEB_PORT \

    --workers $WORKERS \

    --threads $THREADS \

    $SSL_ARGS \

    --access-logfile - \

    --error-logfile - \

    --capture-output