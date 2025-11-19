# devmin：开发者最小栈

面向 Windows Docker Desktop（Linux Engine）为主、macOS Docker Desktop 为辅的研发场景，将原系统拆成 **采集**、**解析落盘**、**Web/控制台** 三个容器。所有容器内部均只访问 `localhost`，通过 `socat` 转发到解析容器，避免暴露任何互联网 IP。

> ⚠️ Docker Desktop 的 `network_mode: host` 在 Windows/macOS 上不可用，因此无法直接在不同容器内通过 `localhost` 互访。本方案使用端口转发进程封装这一差异，对 `data_receive.py` 等代码保持零改动。

## 目录

```
devmin/
 ├─ collector.Dockerfile      # data_receive.py + localhost→parser 转发
 ├─ parser_store.Dockerfile   # mosquitto + raw_parser_service + sink
 ├─ webstack.Dockerfile       # bridge + webapp(app.py/config console)
 ├─ docker-compose.yml        # 最小三容器编排
 ├─ .env.example              # 可选端口/绑定配置
 ├─ config/
 │   └─ collector.config.ini  # 采集端专用 config.ini，默认 broker=localhost
 ├─ scripts/                  # 各容器入口脚本（处理多进程与清理）
 ├─ requirements/             # Web/Bridge 组合依赖
 └─ data/                     # 默认挂载目录（MQTT 落盘/MQTT 数据/采集日志）
```

## 服务拆分

| 服务 | 进程 | 说明 |
| ---- | ---- | ---- |
| `parser` | `mosquitto`、`server/raw_parser_service.py`、`app/sink.py` | MQTT broker（1883/9001）+ 原始帧解析 + CSV 落盘，一切进程只连 `localhost` |
| `collector` | `data_receive.py` + `socat` | UDP→MQTT 采集，不修改源码；容器内 `localhost:1883` 被 `socat` 转发到 `parser` |
| `web` | `server/bridge.py`、`webapp/app.py` + `socat` | 提供 5000（仪表盘）、5002（控制台）、5001（Bridge API）；桥接 MQTT 同样通过转发保持 `localhost` 地址 |

数据收集的起止即为 `collector` 容器的启动/停止：只要 `collector` 运行就表示正在接收 UDP 并写入 MQTT Broker；`docker compose stop collector` 立刻终止收数。

## 快速使用

1. 可选：复制并调整 `.env`：
   ```powershell
   cd C:\Users\CNLab\mqtt_test
   copy devmin\.env.example devmin\.env
   # 根据需要修改端口（默认全部绑定到 127.0.0.1）
   ```
2. 启动最小栈（第 1 次会自动构建三类镜像）：
   ```powershell
   docker compose -f devmin/docker-compose.yml up -d --build
   ```
3. 浏览器访问：
   - 仪表盘：http://localhost:${DEVMIN_WEB_PORT:-5000}
   - 下发控制台：http://localhost:${DEVMIN_CONSOLE_PORT:-5002}
4. 停止全部服务：
   ```powershell
   docker compose -f devmin/docker-compose.yml down
   ```
5. 只暂停或恢复采集：
   ```powershell
   docker compose -f devmin/docker-compose.yml stop collector    # 终止收数
   docker compose -f devmin/docker-compose.yml start collector   # 重新开始
   ```

> 💡 Windows/macOS Docker Desktop 默认只监听 127.0.0.1，可通过 `.env` 中 `DEVMIN_UDP_BIND=0.0.0.0` 允许同一局域网的设备将 UDP 帧发送到开发者机器。

## 映射目录

| 容器 | 挂载路径 | 主机路径 | 用途 |
| ---- | ---- | ---- | ---- |
| parser | `/workspace/app, /workspace/server` | `../app`,`../server` | 热更新 Python 源码 |
| parser | `/workspace/data/mqtt_store` | `devmin/data/mqtt_store` | `sink.py` 输出 CSV |
| parser | `/mosquitto` | `devmin/data/mosquitto` | Broker 数据/日志 |
| collector | `/workspace/app`、`/workspace/data_receive.py` | `../app`, `../data_receive.py` | 复用现有采集逻辑 |
| collector | `/workspace/output` | `devmin/data/collector` | 可选日志/缓存 |
| web | `/workspace/server`、`/workspace/webapp`、`/workspace/app` | 同名目录 | 浏览器 UI 与桥 |

## 常见定制

- **端口 / 绑定地址**：在 `devmin/.env` 中调整 `DEVMIN_*` 变量后，重新运行 `docker compose up -d`.
- **UDP 监听**：默认只监听本机。若需要局域网终端发送数据，将 `DEVMIN_UDP_BIND=0.0.0.0` 并确保系统防火墙允许 13250/UDP。
- **停止后落盘数据**：CSV 位于 `devmin/data/mqtt_store/<DN>/<YYYYMMDD>/data.csv`，可直接使用宿主机工具分析。
- **日志定位**：`docker compose -f devmin/docker-compose.yml logs -f parser|collector|web`.

## 限制与兼容性

1. Windows/macOS 缺少 `host` 网络模式，所以 `collector`、`web` 容器里通过 `socat` 把 `localhost` 代理到 `parser`。如在原生 Linux 上部署，可将 `BROKER_FORWARD_ENABLED=0` 并改用 `network_mode: host`。
2. 端口全部绑定在 127.0.0.1，上线前需显式更改绑定地址或借助反向代理。
3. 镜像基于 `python:3.11-slim`，默认拉取 x86_64 Linux 层。如需 ARM64（Apple Silicon），Docker 会自动拉取对应多架构层。

如需进一步扩展（例如启用 TLS、拆分 parser/store），可在本目录新增 Compose profile、或继续沿用根目录的完整 `docker-compose.yml`。
