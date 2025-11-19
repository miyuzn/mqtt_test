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
- 构建 MQTT Broker（基于 mosquitto，提供纯粹的消息转发能力）；
- 启动 Python Client（自动执行 `sink.py` 完成落盘）；
- 启动 Raw→Parsed 解析服务（server/raw_parser_service.py），在 Broker 内部把 1883 端口收到的二进制流解析后经 9001 端口发布 JSON；
- 启动 MQTT → Web 桥接服务（`server/bridge.py`）；
- 启动 Web 前端（`webapp/`，同时提供实时仪表盘与新的配置调试页面）。

启动完成后可查看运行状态：
```bash
docker ps
```

---

## 🧱 Transfer / Processing 分离部署

若需要像 `sys_stru.png` 中那样将 Broker/Bridge/Parser 部署在 **Transfer Server**，将 PyClient 落盘与 Web UI 部署在 **Data Processing Server**，可使用下面两个 Compose 文件：

### Transfer Server（MQTT Broker + Parser + Bridge）
```bash
docker compose -f docker-compose.transfer.yml up -d
```
- 该 compose 会启动 `mosquitto`、`parser`、`bridge` 三个容器，并将 1883、9001、5001 端口暴露给 Processing Server 使用；
- 不需要额外 IP 配置，Transfer Server 的公网/内网地址由宿主机决定，供其它服务器引用。

### Data Processing Server（PyClient 落盘 + Web）
1. 复制示例环境文件并填写 **Transfer / Processing 两台服务器的地址**：
   ```bash
   cp .env.processing.example .env.processing
   ```
   - 顶部 **Transfer / Processing Server Addresses** 区块记录两台机器：`TRANSFER_SERVER_HOST`（运行 `docker-compose.transfer.yml` 的服务器）以及 `PROCESSING_SERVER_HOST`（运行 `docker-compose.processing.yml` 的服务器，通常供浏览器访问 5000/5002 端口）；后续若服务器更换，只需修改这一段；
   - `TRANSFER_MQTT_HOST` / `CONFIG_BROKER_HOST`：Processing Server 访问 Transfer Server 上 mosquitto 的地址与端口，保持与 `TRANSFER_SERVER_HOST` 一致即可；
   - `BRIDGE_API_BASE_URL`：Processing Server 访问 Transfer Server 上桥接服务（5001 HTTP）的地址。
2. 运行：
   ```bash
   docker compose --env-file .env.processing -f docker-compose.processing.yml up -d
   ```
- `.env.processing` 中即可指定 Processing Server 需要连接的 Transfer Server IP；若未来 Bridge、Broker 再次拆分，只需把对应地址改成新的服务器。

> 如仍需本机一键启动全部容器，可继续使用 `docker-compose.yml`。

### 4️⃣ 访问实时监控仪表盘

Web 服务会同步订阅 MQTT 数据，并通过 Socket.IO 将压力数据推送至浏览器。默认访问地址：

- http://localhost:5000

### 5️⃣ ESP32 配置下发（调试控制台）

配置下发链路已迁移到 Web 服务，由 Web 端主导指令生成，发送端 `data_receive.py` 负责落地执行：

1. 调试入口：http://localhost:5002（与用户仪表盘 5000 端口隔离，仅供研发使用）。
2. Web 页面输入 `DN`、analog/select 引脚后，会通过 MQTT 主题 `etx/v1/config/cmd` 发布指令。
3. 每个发送端实例（运行 `data_receive.py` 的主机）会维护 `DN → IP` 的实时映射，只有持有该 DN 的发送端会响应指令：
   - 发送端解析 payload，按 `te.py` 的规则校验 analog/select 数量与 512 字节限制；
   - 通过本地 TCP 连到目标设备（默认端口 `22345`，可在 `config.ini` 的 `[CONFIG]` 段调整），发送 JSON 并等待回包；
   - 执行结果会发布到 `etx/v1/config/result/<agent_id>/<command_id>`，Web 控制台实时展示发送状态与设备回执。
4. 发送端还会定期把自身可控的设备列表广播到 `etx/v1/config/agents/<agent_id>`（使用保留消息），Web 控制台据此列出在线 DN、IP 以及最后更新时间。

> 如需修改主题或 TCP 端口，请参考根目录 `config.ini` 的 `[CONFIG]` 段，或通过环境变量覆盖 `CONFIG_CMD_TOPIC` / `CONFIG_RESULT_TOPIC` / `CONFIG_AGENT_TOPIC` / `DEVICE_TCP_PORT` 等值。

---

## 🧮 解析链路调整

- Android / PC 侧的 `data_receive.py` 现在默认只发布原始二进制帧到 `etx/v1/raw`，如需本地解析可手动开启 `PUBLISH_PARSED`。
- `server/raw_parser_service.py` 常驻 Broker 侧：它通过 1883 端口订阅原始流，解析后由 9001（WebSocket）端口重新发布 JSON。
- Web 仪表盘及其下游继续订阅 `etx/v1/parsed/#`，无需改动，即可自动享受服务端解析带来的性能收益。

---

## 📡 GCU 广播/单播握手流程

- **设备端（GCU）** 默认向 `255.255.255.255:13250` 广播数据帧；一旦收到正文为 `GCU_SUBSCRIBE` 的 UDP 包，会立即回 `GCU_ACK` 并将后续采集数据切换为对该源 IP/端口的单播；若 20 秒未再收到心跳或收到了 `GCU_BROADCAST`，设备会回退到广播模式。
- **采集端（Android/PC 的 `data_receive.py`）** 监听 13250 端口：首次收到广播帧时立刻向源地址发送 `GCU_SUBSCRIBE`，收到 `GCU_ACK` 视为握手成功，并且每 5 秒发送一次心跳（同样是 `GCU_SUBSCRIBE`）确保链路保持单播；需要恢复广播时，可显式向设备发送 `GCU_BROADCAST`。
- 所有握手参数（令牌文本、心跳/超时时间、退出时是否自动广播）都可以在 `config.ini` 的 `[GCU]` 段配置，Android 端默认与 Python 端保持一致，因此无需额外配置即可实现自动握手/心跳。

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
PUBLISH_RAW = 1
PUBLISH_PARSED = 0

[CONFIG]
CMD_TOPIC = etx/v1/config/cmd
RESULT_TOPIC = etx/v1/config/result
AGENT_TOPIC = etx/v1/config/agents
DEVICE_TCP_PORT = 22345
DEVICE_TCP_TIMEOUT = 3.0

[GCU]
ENABLED = 1
SUBSCRIBE_TOKEN = GCU_SUBSCRIBE
ACK_TOKEN = GCU_ACK
BROADCAST_TOKEN = GCU_BROADCAST
HEARTBEAT_SEC = 5
FALLBACK_SEC = 20
BROADCAST_ON_EXIT = 1

[PARSER]
RAW_BROKER_HOST = mosquitto
RAW_BROKER_PORT = 1883
RAW_TOPIC = etx/v1/raw/#
PARSED_BROKER_HOST = mosquitto
PARSED_BROKER_PORT = 9001
PARSED_TRANSPORT = websockets
PARSED_TOPIC_PREFIX = etx/v1/parsed
PARSED_QOS = 1
```

如需连接远程 Broker，请修改 `BROKER_HOST` 为服务器 IP 或域名。

---

## 🧹 目录结构

```text
.
├── app/
│   ├── Dockerfile
│   ├── requirements.txt                # Python 客户端依赖（含 bridge 依赖）
│   ├── sink.py                         # 模块4：MQTT 落盘
│   ├── sensor2.py                      # 数据解析逻辑
│   └── mqtt_store/                     # CSV 数据存储
├── mosquitto/
│   ├── config/mosquitto.conf           # 纯 mosquitto 配置
│   ├── data/                           # 持久化数据
│   └── log/                            # 日志输出
├── server/
│   └── bridge.py                       # 模块3/4：MQTT → Web 实时桥接
│   └── raw_parser_service.py          # 1883→9001 原始数据解析下行
├── webapp/
│   ├── Dockerfile
│   ├── app.py                          # 模块5：Flask Web（仪表盘 + 配置调试）
│   ├── requirements.txt
│   ├── config_backend.py               # 配置 MQTT 客户端/状态管理
│   ├── templates/index.html            # 实时仪表盘
│   ├── templates/config_console.html   # 调试控制台页面
│   └── static/                         # 仪表盘 & 调试页资源
├── docker-compose.yml                  # 一键部署 docker 配置脚本
├── config.ini                          # UDP → MQTT 发送端配置
├── data_receive.py                     # 模块2：UDP→MQTT 桥接
└── README.md
```

---

## 🔁 配置下发架构（MQTT 流向）

1. **控制台发出命令**：`webapp` 在端口 `5002` 提供调试页面，提交后会向 `CONFIG_CMD_TOPIC`（默认 `etx/v1/config/cmd`）发布 JSON 指令，包含 `command_id`、`target_dn`、`analog`、`select` 与可选操作者。
2. **发送端匹配设备**：每个运行 `data_receive.py` 的发送端都会：
   - 根据收到的 UDP 数据解析 `dn_hex`，维护 `DN → IP` 的缓存；
   - 周期性地把自身掌握的设备列表推送到 `CONFIG_AGENT_TOPIC/<agent_id>`（默认 `etx/v1/config/agents/<agent_id>`，使用保留消息），供 Web 控制台展示。
3. **指令执行**：拥有目标 DN 的发送端会：
   - 按 `te.py` 规则校验 analog/select，并把 payload 透传给目标设备（默认 `TCP :22345`）；
   - 收集设备回执或错误信息，并在 `CONFIG_RESULT_TOPIC/<agent_id>/<command_id>`（默认 `etx/v1/config/result/...`）上发布执行结果。
4. **后台收集结果**：`webapp` 内置的 `config_backend` MQTT 客户端会同时订阅 agent 状态与执行结果，刷新调试页面列表，并把响应与失败信息保存 50 条滚动历史。

> 以上三个主题均可通过 `config.ini` 或环境变量（`CONFIG_CMD_TOPIC` 等）覆写。

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
- Parsed WebSocket：ws://localhost:9001/mqtt (由 parser 服务广播)
- MQTT-Web 桥接：http://localhost:5001
- Web 可视化（仪表盘）：http://localhost:5000
- 配置调试控制台：http://localhost:5002
```

> 调试控制台需要发送端维护的 DN→IP 映射。若列表中没有目标设备，请确认 `data_receive.py` 与设备之间存在 UDP 流，并等待 1~2 个采样周期让映射刷新。

可使用 [MQTTX](https://mqttx.app/) 或命令行工具进行测试 MQTT 消息：
```bash
mosquitto_sub -h localhost -t "etx/v1/parsed/#" -v
```

在浏览器打开 `http://localhost:5000` 可以看到实时压力仪表板，页面通过 Server-Sent Events 自动刷新。

---

## 📄 License

© 2025 iSensing Lab. All rights reserved.

