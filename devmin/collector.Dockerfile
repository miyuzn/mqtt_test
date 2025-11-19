# syntax=docker/dockerfile:1.6
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends bash socat ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY app/requirements.txt /tmp/app-requirements.txt
RUN pip install --no-cache-dir -r /tmp/app-requirements.txt

COPY devmin/scripts/collector_entry.sh /usr/local/bin/start-collector.sh
RUN chmod +x /usr/local/bin/start-collector.sh

ENTRYPOINT ["/usr/local/bin/start-collector.sh"]
