FROM python:3.11-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /web

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN sed -i 's/\r$//' web_entrypoint.sh && chmod +x web_entrypoint.sh

CMD ["./web_entrypoint.sh"]
