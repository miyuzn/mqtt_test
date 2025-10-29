import time
import paho.mqtt.client as mqtt
from utils import getenv_str, getenv_int

BROKER_HOST = getenv_str("BROKER_HOST", "mosquitto")
BROKER_PORT = getenv_int("BROKER_PORT", 1883)
USERNAME    = getenv_str("USERNAME", "")
PASSWORD    = getenv_str("PASSWORD", "")
PUB_TOPIC   = getenv_str("PUB_TOPIC", "demo/hello")

def build_client() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="py-publisher")
    if USERNAME:
        client.username_pw_set(USERNAME, PASSWORD or None)
    return client

def main():
    client = build_client()
    while True:
        try:
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
            break
        except Exception as e:
            print("[publisher] Broker not ready, retrying...", e)
            time.sleep(1)

    # 每 2 秒发一条测试消息
    i = 0
    while True:
        payload = f"hello #{i} from publisher in container"
        r = client.publish(PUB_TOPIC, payload, qos=0, retain=False)
        print(f"[publisher] -> {PUB_TOPIC}: {payload} (rc={r.rc})")
        i += 1
        time.sleep(2)

if __name__ == "__main__":
    main()
