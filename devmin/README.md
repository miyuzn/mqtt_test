# devmin：开发者最小栈（parser + sink + web）

面向 **Windows Docker Desktop（Linux Engine）** 与 **macOS Docker Desktop** 的快速联调场景，`devmin` 目录提供只包含 “解析（含 MQTT Broker）”、“落盘” 与 “Web/控制台” 三个容器的 Compose。**数据采集依旧在宿主机运行 `data_receive.py`**，避免容器无法监听外部 UDP 的限制。

> ⚠️ Windows/macOS 无法使用 `network_mode: host`，因此 web 容器仍借助 `socat` 将 `localhost` 代理到 parser 容器；宿主机运行的 `data_receive.py` 则直接连接 `127.0.0.1:1883`。

## 目录结构

```
devmin/
 ├─ data_receive_local.py     # 本地主机运行 data_receive.py 的入口
 ├─ parser_store.Dockerfile   # mosquitto + raw_parser_service
 ├─ sink.Dockerfile           # 独立落盘容器
 ├─ webstack.Dockerfile       # bridge + webapp(app.py/config console)
 ├─ docker-compose.yml        # parser + sink + web
 ├─ .env.example              # 可选端口映射配置
 ├─ scripts/                  # 多进程入口脚本
 ├─ requirements/             # Web/Bridge 组合依赖
 ├─ config/
 │   └─ data_receive.dev.ini  # devmin 默认配置（MQTT=127.0.0.1:1883）
 └─ data/                     # 默认挂载目录（mqtt_store、mosquitto 数据）
```

## 服务拆分

| 单元 | 运行位置 | 进程/内容 | 说明 |
| ---- | ---- | ---- | ---- |
| parser | 容器 | `mosquitto`、`server/raw_parser_service.py` | 负责 MQTT broker（1883/9001）及原始→JSON 解析。 |
| sink | 容器 | `app/sink.py` | 独立落盘服务，订阅 `etx/v1/raw/#` 并写入 `devmin/data/mqtt_store`。 |
| web | 容器 | `server/bridge.py`、`webapp/app.py` + `socat` | 提供 5001（Bridge API）、5000（仪表盘）、5002（配置控制台）。 |
| collector | 宿主机 | `data_receive.py` | 直接监听 UDP，向 parser 暴露的 1883 端口写入数据。 |

## 快速使用

1. **可选：配置端口**
   ```powershell
   cd C:\Users\CNLab\mqtt_test
   copy devmin\.env.example devmin\.env
   # 根据需要调整 DEVMIN_MQTT_PORT / DEVMIN_WEB_PORT / DEVMIN_CONSOLE_PORT / DEVMIN_BRIDGE_PORT
   ```
2. **启动最小栈（首次会自动构建镜像）**
   ```powershell
   docker compose -f devmin/docker-compose.yml up -d --build
   ```
3. **宿主机运行 `data_receive_local.py`（采集起点）**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r app/requirements.txt
   python devmin/data_receive_local.py
   ```
   `Ctrl+C` 即为采集终点。
4. **访问页面**
   - 仪表盘：http://localhost:${DEVMIN_WEB_PORT:-5000}
   - 控制台：http://localhost:${DEVMIN_CONSOLE_PORT:-5002}
5. **停止服务**
   ```powershell
   docker compose -f devmin/docker-compose.yml down
   ```

## 映射目录

| 服务 | 容器路径 | 主机路径 | 用途 |
| ---- | ---- | ---- | ---- |
| parser | `/workspace/app`, `/workspace/server` | `../app`, `../server` | 解析服务热更新 |
| parser | `/workspace/data/mqtt_store` | `devmin/data/mqtt_store` | 与 sink 共用落盘目录 |
| parser | `/mosquitto` | `devmin/data/mosquitto` | Broker 数据/日志 |
| sink | `/workspace/app` | `../app` | 复用 sink.py 代码 |
| sink | `/workspace/data/mqtt_store` | `devmin/data/mqtt_store` | CSV 输出目录 |
| web | `/workspace/server`, `/workspace/webapp`, `/workspace/app` | 对应源码目录 | Web/Bridge 热更新 |

## 宿主机采集端注意事项

1. 建议通过 `python devmin/data_receive_local.py` 启动，它会：
   - 将 `CONFIG_PATH` 指向 `devmin/config/data_receive.dev.ini`;
   - 自动设置 `MQTT_BROKER_HOST/BROKER_HOST=127.0.0.1`（可继续被环境变量覆盖）。
2. 若手动运行 `python data_receive.py`，请确保 `[MQTT] BROKER_HOST` 与 parser 暴露的端口一致。
3. 采集端运行在宿主机，可继续监听 `0.0.0.0:13250` 等端口，不受容器限制。
4. 执行脚本即视为采集开始，`Ctrl+C` 为采集终点。

## 常见定制

- **端口/绑定地址**：修改 `devmin/.env` 后重新 `docker compose up -d` 使其生效。
- **实时写盘**：sink 容器通过 `SINK_FLUSH_EVERY_ROWS=1` 实现逐行刷新；如需批量刷新，可调整该值。
- **日志排查**：`docker compose -f devmin/docker-compose.yml logs -f parser|sink|web`；采集端日志直接在本地终端查看。

## 限制

1. Windows/macOS 缺失 host 网络模式，web 容器仍依赖 `socat` 访问 parser。若在 Linux 本机部署，可改用 `network_mode: host` 并关闭 `socat`。
2. 默认端口仅绑定 127.0.0.1，如需局域网访问须自行配置端口映射或反代。
3. 镜像基于 `python:3.11-slim`，支持 x86_64/arm64 多架构。
