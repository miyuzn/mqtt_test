# === run_bridge_conda.ps1 ===
conda activate base
python -m pip install --upgrade pip
python -m pip install paho-mqtt==2.1.0

$env:MQTT_BROKER_HOST = "127.0.0.1"
$env:MQTT_BROKER_PORT = "1883"
$env:UDP_LISTEN_PORT  = "13250"
$env:DEVICE_ID        = "R25"
$env:MQTT_TOPIC_RAW   = "etx/v1/raw/R25"

python .\receive_mqtt.py
