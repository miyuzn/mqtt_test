import time
import paho.mqtt.client as mqtt
from utils import getenv_str, getenv_int

"""
Simple MQTT publisher inside the container to send heartbeat messages.
简单的容器内 MQTT 发布脚本，用于持续发送心跳消息，方便联调。
"""


BROKER_HOST = getenv_str("BROKER_HOST", "mosquitto")
BROKER_PORT = getenv_int("BROKER_PORT", 1883)
USERNAME = getenv_str("USERNAME", "")
PASSWORD = getenv_str("PASSWORD", "")
PUB_TOPIC = getenv_str("PUB_TOPIC", "demo/hello")


def build_client() -> mqtt.Client:
    # Initialize MQTT client and optional auth for automated testing flows.
    # 初始化 MQTT 客户端并按需设置认证信息，方便自动化联调。
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
        except Exception as exc:
            # Keep retrying until the broker is ready.
            # 一直重试直到代理启动完成。
            print("[publisher] Broker not ready, retrying...", exc)
            time.sleep(1)

    # Publish one demo message every two seconds to act as a heartbeat.
    # 以 2 秒周期发布示例消息，作为链路健康的“心跳”。
    i = 0
    while True:
        payload = f"hello #{i} from publisher in container"
        result = client.publish(PUB_TOPIC, payload, qos=0, retain=False)
        print(f"[publisher] -> {PUB_TOPIC}: {payload} (rc={result.rc})")
        i += 1
        time.sleep(2)


if __name__ == "__main__":
    main()
