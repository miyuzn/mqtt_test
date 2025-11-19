# syntax=docker/dockerfile:1.6
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends bash socat ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY devmin/requirements/webstack.txt /tmp/webstack-requirements.txt
RUN pip install --no-cache-dir -r /tmp/webstack-requirements.txt

COPY devmin/scripts/webstack_entry.sh /usr/local/bin/start-webstack.sh
RUN chmod +x /usr/local/bin/start-webstack.sh

ENTRYPOINT ["/usr/local/bin/start-webstack.sh"]
