# 🧠 MQTT PyClient System

本项目用于运行 **MQTT Python Client 环境**，可实现 UDP → MQTT 数据桥接、订阅与消息分析。  
项目基于 Docker 快速部署，无需额外安装依赖。

---

## 🚀 部署步骤

### 1️⃣ 克隆项目仓库
```bash
git clone https://github.com/miyuzn/mqtt_test.git
cd mqtt_test
```

> 💡 若你已获取压缩包，可直接解压后进入项目目录。

---

### 2️⃣ 确认本地已安装 Docker 环境
请确保本机已正确安装以下组件：

- [Docker Engine / Docker Desktop](https://www.docker.com/get-started/)

测试命令：
```bash
docker --version
docker compose version
```

若两条命令均能输出版本号，即表示环境准备完毕。

---

### 3️⃣ 一键启动容器
在项目根目录下运行：

```bash
docker compose up -d
```

Compose 将自动：
- 拉取所需镜像（官方 `eclipse-mosquitto` 与 `miyuzn/mqtt_test-pyclient:latest`）；
- 启动 MQTT Broker；
- 启动 Python Client（自动执行 `sink.py`）；
- 按配置文件连接内部网络。

启动完成后可查看运行状态：
```bash
docker ps
```

---

## ⚙️ 默认配置说明

项目根目录中包含 `config.ini` 文件，用于定义 UDP 与 MQTT 参数：

```ini
[UDP]
LISTEN_PORT = 13250

[MQTT]
BROKER_HOST = mosquitto
BROKER_PORT = 1883
TOPIC_PARSED_PREFIX = etx/v1/parsed
```

如需连接远程 Broker，请修改 `BROKER_HOST` 为服务器 IP 或域名。

---

## 🧹 目录结构

```text
.
├── app/
│   ├── mqtt_store/                     # 接收到的数据
│   │   └── <device:Mac address>/       # 同一device接收到的数据
│   │        └── <date>/                # 同一天接收到的数据
│   │             └── <hhmmss>.csv      # 单次实验接收到的数据
│   ├── sensor2.py                      # 传感器数据类
│   ├── sink.py                         # MQTT接收方脚本
│   └── config.ini                      # MQTT接收方配置文件
├── docker-compose.yml                  # 一键部署docker配置脚本
├── config.ini                          # MQTT发送方配置文件
├── data_receive.py                     # MQTT发送方脚本
└── README.md                           # 项目说明
```

---

## 🛠 常用命令

查看容器日志：
```bash
docker compose logs -f
```

停止容器：
```bash
docker compose down
```

重建容器：
```bash
docker compose up -d --build
```

---

## 📡 MQTT 测试

默认 Broker 暴露在本机端口：
```
tcp://localhost:1883
```

可使用 [MQTTX](https://mqttx.app/) 或命令行工具进行测试：
```bash
mosquitto_sub -h localhost -t "etx/v1/parsed/#" -v
```

---

## 📄 License

© 2025 iSensing Lab. All rights reserved.

