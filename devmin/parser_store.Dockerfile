# syntax=docker/dockerfile:1.6
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends bash mosquitto mosquitto-clients ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY backend/requirements.txt /tmp/app-requirements.txt
RUN pip install --no-cache-dir -r /tmp/app-requirements.txt

COPY broker/config/mosquitto.conf /etc/mosquitto/mosquitto.conf
COPY devmin/scripts/parser_entry.sh /usr/local/bin/start-parser-stack.sh
RUN chmod +x /usr/local/bin/start-parser-stack.sh

ENTRYPOINT ["/usr/local/bin/start-parser-stack.sh"]
