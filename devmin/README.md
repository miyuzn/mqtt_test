# devmin：开发者最小栈（parser + web，两容器）

针对以 **Windows Docker Desktop（Linux Engine）** 为主、**macOS Docker Desktop** 为辅的研发环境，`devmin` 目录提供仅包含 “解析+落盘” 与 “Web/控制台” 两个容器的 Compose。**数据采集仍由宿主机运行的 `data_receive.py` 负责**，以避免容器内无法正确侦听外部 UDP 数据的问题。

> ⚠️ Windows/macOS 上的 `network_mode: host` 不可用，因此容器内部依旧通过 `socat` 把 `localhost` 转发到解析容器；宿主机运行的 `data_receive.py` 直接连接 `127.0.0.1:1883`。

## 目录结构

```
devmin/
 ├─ parser_store.Dockerfile   # mosquitto + raw_parser_service + sink
 ├─ webstack.Dockerfile       # bridge + webapp(app.py/config console)
 ├─ docker-compose.yml        # 仅 parser + web 两个服务
 ├─ .env.example              # 可选端口映射配置
 ├─ scripts/                  # 多进程入口脚本
 ├─ requirements/             # Web/Bridge 组合依赖
 └─ data/                     # 默认挂载目录（mqtt_store、mosquitto 数据）
```

## 服务拆分

| 单元 | 运行位置 | 进程/内容 | 说明 |
| ---- | ---- | ---- | ---- |
| parser | 容器 | `mosquitto`、`server/raw_parser_service.py`、`app/sink.py` | MQTT broker（1883/9001）、原始→JSON 解析、CSV 落盘。所有进程只访问容器内 `localhost`。 |
| web | 容器 | `server/bridge.py`、`webapp/app.py` + `socat` | 提供 5001（Bridge API）、5000（仪表盘）、5002（配置控制台）；MQTT 访问通过 `socat` 保持 `localhost`。 |
| collector | 宿主机 | `data_receive.py` | 直接在开发者主机运行，监听 UDP 并将数据写入 `parser` 暴露的 1883 端口。 |

## 快速使用

1. **可选：配置端口**  
   ```powershell
   cd C:\Users\CNLab\mqtt_test
   copy devmin\.env.example devmin\.env
   # 根据需要调整 DEVMIN_MQTT_PORT / DEVMIN_WEB_PORT / DEVMIN_CONSOLE_PORT / DEVMIN_BRIDGE_PORT
   ```

2. **启动解析+Web 栈（首次会自动构建镜像）**  
   ```powershell
   docker compose -f devmin/docker-compose.yml up -d --build
   ```

3. **在宿主机启动 `data_receive.py`（采集起点）**  
   - 准备虚拟环境并安装依赖：
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\activate
     pip install -r app/requirements.txt
     ```
   - 确认 `config.ini` 中 `[MQTT] BROKER_HOST` 改为 `127.0.0.1`（或设置环境变量 `MQTT_BROKER_HOST=127.0.0.1`）。
   - 运行：
     ```powershell
     python data_receive.py
     ```
   - 当需要结束采集时，`Ctrl+C` 即为采集终点。

4. **访问页面**
   - 仪表盘：http://localhost:${DEVMIN_WEB_PORT:-5000}
   - 下发控制台：http://localhost:${DEVMIN_CONSOLE_PORT:-5002}

5. **停止容器栈**
   ```powershell
   docker compose -f devmin/docker-compose.yml down
   ```

## 映射目录

| 服务 | 容器路径 | 主机路径 | 描述 |
| ---- | ---- | ---- | ---- |
| parser | `/workspace/app`, `/workspace/server` | `../app`, `../server` | 共享源码，支持热更新 |
| parser | `/workspace/data/mqtt_store` | `devmin/data/mqtt_store` | `sink.py` 输出 CSV |
| parser | `/mosquitto` | `devmin/data/mosquitto` | Broker 数据/日志 |
| web | `/workspace/server`, `/workspace/webapp`, `/workspace/app` | 对应源码目录 | Web/Bridge 热更新 |

## 宿主机采集端注意事项

1. **MQTT 目标**：`data_receive.py` 的 `BROKER_HOST` 应配置为 `127.0.0.1`，端口与 `DEVMIN_MQTT_PORT` 一致（默认为 1883）。文件配置优先：  
   ```ini
   [MQTT]
   BROKER_HOST = 127.0.0.1
   BROKER_PORT = 1883
   ```
   或在启动前 `setx MQTT_BROKER_HOST 127.0.0.1`。
2. **UDP 监听**：采集端仍在宿主机执行，可继续监听 0.0.0.0:13250 等端口，不再受到容器网络限制。
3. **打点时间段**：`python data_receive.py` 启动时即视为采集开始，按 `Ctrl+C` 结束（脚本会捕获信号并做清理）。

## 常见定制

- **端口/绑定地址**：修改 `devmin/.env` 后重新 `docker compose up -d`，即可更换 MQTT/Web 端口。宿主机 `data_receive.py` 需同步指向新端口。
- **数据持久化**：所有 CSV 均输出在 `devmin/data/mqtt_store/<DN>/<YYYYMMDD>/data.csv`。
- **日志排查**：`docker compose -f devmin/docker-compose.yml logs -f parser` / `logs -f web`；采集端日志直接在本地终端查看。

## 限制与兼容性

1. Windows/macOS 无法使用 `network_mode: host`，`web` 容器仍通过 `socat` 访问 `parser`。在原生 Linux 上可以把 `BROKER_FORWARD_ENABLED` 设为 0 并自行开启 host 网络。
2. 所有端口仅绑定 `127.0.0.1`，若需局域网访问，需自行在 Docker Desktop 侧暴露或通过反向代理。
3. 镜像基于 `python:3.11-slim`，支持 x86_64/arm64 多架构。

如需进一步扩展（TLS、分布式部署等），可继续沿用根目录 `docker-compose.yml` 或在 `devmin` 中新增 profile。
