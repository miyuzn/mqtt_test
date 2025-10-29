import time
import paho.mqtt.client as mqtt
from utils import getenv_str, getenv_int, parse_topics

BROKER_HOST = getenv_str("BROKER_HOST", "mosquitto")
BROKER_PORT = getenv_int("BROKER_PORT", 1883)
USERNAME    = getenv_str("USERNAME", "")
PASSWORD    = getenv_str("PASSWORD", "")
SUB_TOPICS  = parse_topics(getenv_str("SUB_TOPICS", "demo/#"))

def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[subscriber] Connected rc={reason_code}")
    for t in SUB_TOPICS:
        client.subscribe(t)
        print(f"[subscriber] Subscribed: {t}")

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8", errors="ignore")
    except Exception:
        payload = str(msg.payload)
    print(f"[{msg.topic}] {payload}")

def build_client() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="py-subscriber")
    client.on_connect = on_connect
    client.on_message = on_message
    if USERNAME:
        client.username_pw_set(USERNAME, PASSWORD or None)
    return client

def main():
    client = build_client()
    while True:
        try:
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
            break
        except Exception as e:
            print("[subscriber] Broker not ready, retrying...", e)
            time.sleep(1)
    client.loop_forever()

if __name__ == "__main__":
    main()
