FROM python:3.11-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码热挂载，仍复制一份避免空卷覆盖（开发期无所谓）
COPY . .

# 开发期让 compose 用 sleep infinity 保持容器存活
# 如需直接启动订阅者，可改为：
# CMD ["python", "main_subscriber.py"]
CMD ["python", "sink.py"]