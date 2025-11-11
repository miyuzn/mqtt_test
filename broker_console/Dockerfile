FROM eclipse-mosquitto:2

RUN apk add --no-cache python3 py3-pip bash

WORKDIR /console

COPY requirements.txt /console/requirements.txt
RUN python3 -m venv /opt/console-venv && \
    . /opt/console-venv/bin/activate && \
    pip install --no-cache-dir -r /console/requirements.txt
ENV PATH="/opt/console-venv/bin:${PATH}"

COPY app /console/app
COPY frontend /console/frontend
COPY state /console/state
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1     CONSOLE_STATE_DIR=/console/state     CONSOLE_HISTORY_PATH=/console/state/config-history.json

EXPOSE 5080

CMD ["/bin/bash", "/entrypoint.sh"]
