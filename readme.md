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
- 构建带控制台的 MQTT Broker（整合 mosquitto + FastAPI 配置下发服务）；
- 启动 Python Client（自动执行 `sink.py` 完成落盘）；
- 启动 MQTT → Web 桥接服务（`server/bridge.py`）；
- 启动 Web 前端（`webapp/`，展示实时压力数据）。

启动完成后可查看运行状态：
```bash
docker ps
```

### 4️⃣ 访问实时监控仪表盘

Web 服务会同步订阅 MQTT 数据，并通过 Socket.IO 将压力数据推送至浏览器。默认访问地址：

- http://localhost:5000

### 5️⃣ ESP32 配置下发（开发者控制台）

Broker 容器内新增了一个 FastAPI + 静态前端的“配置控制台”，用于替代手工运行 `te.py`：

- 访问地址：http://localhost:5080
- 功能：自动列出当前活跃的 ESP32（根据 MQTT 数据流自动感知）、可视化选择 analog / select 并一键下发；
- 校验：完全复用了 `te.py` 的引脚数量、取值范围、512 字节（含结尾换行）Payload 限制；
- 图片提示：左侧 IO 示意图引用 `/static/images/pcb-layout.png`，当前提供了 `pcb-layout-placeholder.png`，请将真实 PCB 图替换为同名文件即可；
- MQTT 下发：向 `esp32/config/{dn}`（可通过 `CONFIG_TOPIC_TEMPLATE` 调整）发布 JSON，使用 retained 消息，设备上线立即获取最新配置。

> 如果需要修改订阅的传感器上行 Topic，可在 `docker-compose.yml` 的 `mosquitto` 服务环境变量里调整 `SENSOR_TOPIC_FILTER`。

若修改了 `MQTT_TOPIC` 或 Broker 地址，可在 `docker-compose.yml` 的 `web` 服务环境变量中调整。

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
├── broker_console/
│   ├── Dockerfile                     # mosquitto + 配置控制台
│   ├── app/                           # FastAPI 后端（MQTT 客户端 + API）
│   ├── frontend/                      # 配置下发前端页面
│   ├── requirements.txt
│   └── entrypoint.sh
├── app/
│   ├── Dockerfile
│   ├── requirements.txt                # Python 客户端依赖（含 bridge 依赖）
│   ├── sink.py                         # 模块4：MQTT 落盘
│   ├── sensor2.py                      # 数据解析逻辑
│   └── mqtt_store/                     # CSV 数据存储
├── server/
│   └── bridge.py                       # 模块3/4：MQTT → Web 实时桥接
├── webapp/
│   ├── Dockerfile
│   ├── app.py                          # 模块5：Flask Web 可视化
│   ├── requirements.txt
│   ├── templates/index.html            # 可视化界面
│   └── static/styles.css
├── docker-compose.yml                  # 一键部署 docker 配置脚本
├── config.ini                          # UDP → MQTT 发送端配置
├── data_receive.py                     # 模块2：UDP→MQTT 桥接
└── README.md
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

默认服务暴露端口：
```
- MQTT Broker：tcp://localhost:1883
- MQTT-Web 桥接：http://localhost:5001
- Web 可视化：http://localhost:5000
- 配置下发控制台：http://localhost:5080
```

可使用 [MQTTX](https://mqttx.app/) 或命令行工具进行测试 MQTT 消息：
```bash
mosquitto_sub -h localhost -t "etx/v1/parsed/#" -v
```

在浏览器打开 `http://localhost:5000` 可以看到实时压力仪表板，页面通过 Server-Sent Events 自动刷新。

---

## 📄 License

© 2025 iSensing Lab. All rights reserved.

