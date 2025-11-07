import time
import paho.mqtt.client as mqtt
from utils import getenv_str, getenv_int, parse_topics

"""
Lightweight MQTT subscriber used for smoke testing the broker connection.
轻量级 MQTT 订阅器，用于快速验证代理连接是否可用。
"""

BROKER_HOST = getenv_str("BROKER_HOST", "mosquitto")
BROKER_PORT = getenv_int("BROKER_PORT", 1883)
USERNAME    = getenv_str("USERNAME", "")
PASSWORD    = getenv_str("PASSWORD", "")
SUB_TOPICS  = parse_topics(getenv_str("SUB_TOPICS", "demo/#"))  # 多 topic 以逗号分隔 | Allow comma-separated topics

def on_connect(client, userdata, flags, reason_code, properties=None):
    # Subscribe to all configured topics once the connection is acknowledged.
    # 连接成功后订阅所有预设主题，确保不会错过广播。
    print(f"[subscriber] Connected rc={reason_code}")
    for t in SUB_TOPICS:
        client.subscribe(t)
        print(f"[subscriber] Subscribed: {t}")

def on_message(client, userdata, msg):
    # Decode payload conservatively to avoid crashing on binary frames.
    # 为防止二进制帧导致异常，使用忽略错误的方式解码负载。
    try:
        payload = msg.payload.decode("utf-8", errors="ignore")
    except Exception:
        payload = str(msg.payload)
    print(f"[{msg.topic}] {payload}")

def build_client() -> mqtt.Client:
    # Wire up callbacks and optional authentication.
    # 绑定回调与可选认证信息，保持处理逻辑集中。
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
            # Retry until the broker becomes reachable.
            # 重复重试直至代理端口可达。
            print("[subscriber] Broker not ready, retrying...", e)
            time.sleep(1)
    client.loop_forever()

if __name__ == "__main__":
    main()
