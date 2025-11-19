# Devmin Quickstart / Devmin クイックスタート / Devmin 快速上手

> Developers only. This README focuses on the **devmin** stack (parser + sink + web containers, local collector).

---

## 1. Clone & prerequisites / クローンと前提 / 克隆与前置

- **EN:** `git clone https://github.com/miyuzn/mqtt_test.git && cd mqtt_test`. Install Docker Desktop (Engine + Compose) and Python 3.11 (for local collector).
- **JP:** `git clone https://github.com/miyuzn/mqtt_test.git && cd mqtt_test` を実行し、Docker Desktop（Engine + Compose）と Python 3.11 をインストールしてください。
- **CN:** 执行 `git clone https://github.com/miyuzn/mqtt_test.git && cd mqtt_test`，并确保本机已安装 Docker Desktop（Engine + Compose）与 Python 3.11。

Verify with / 動作確認 / 验证：
```bash
docker --version
docker compose version
python --version
```

---

## 2. Launch devmin containers / devmin コンテナ起動 / 启动 devmin 容器

- **EN:** (optional) copy `devmin/.env.example` → `devmin/.env` to customize ports. Then:
  ```bash
  docker compose -f devmin/docker-compose.yml up -d --build
  ```
- **JP:** 必要に応じ `devmin/.env.example` を `devmin/.env` にコピーしポートを調整後、上記コマンドを実行します。
- **CN:** 如需自定义端口，可先复制 `devmin/.env.example` 为 `devmin/.env`。之后执行同一命令即可启动 parser/sink/web 三个容器。

Check logs / ログ確認 / 查看日志：
```bash
docker compose -f devmin/docker-compose.yml logs -f parser sink web
```

---

## 3. Start local collector / ローカル収集プロセス / 启动本地采集

1. **EN:** Create venv + install deps once:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate  # Windows PowerShell
   pip install -r app/requirements.txt
   ```
2. **JP:** その後 `python devmin/data_receive_local.py` を実行。`CONFIG_PATH` は自動的に `devmin/config/data_receive.dev.ini` へ設定され、MQTT は `127.0.0.1:1883` に接続します。
3. **CN:** 运行 `python devmin/data_receive_local.py` 即视为开始收数，按 `Ctrl+C` 结束（脚本会提示“采集终止”）。

采集生命周期 / 収集ライフサイクル / Collection lifecycle:
- Start script ⇒ sensors begin streaming via UDP → MQTT.
- `Ctrl+C` ⇒ collector stops, sink flushes CSV to `devmin/data/mqtt_store/<DN>/<YYYYMMDD>/`.

---

## 4. Receive data & verify / データ受信確認 / 数据校验

- **EN:** CSV files appear under `devmin/data/mqtt_store`. Tail them or open in Python to confirm content. Example:
  ```bash
  Get-Content devmin/data/mqtt_store/<DN>/<DAY>/<time>.csv
  ```
- **JP:** `docker compose -f devmin/docker-compose.yml logs -f sink` を見ると `[MQTT] connected` や `[STATS] rows_written=...` が表示され、書き込み状況を確認できます。
- **CN:** 若未看到新文件，请检查 `python devmin/data_receive_local.py` 输出以及 `sink` 日志，确认订阅主题 `etx/v1/raw/#` 正在接收数据。

---

## 5. (Optional) Frontend & console / 付録：前端・コンソール / 附加：前端与控制台

- **EN:** The web container exposes:
  - Dashboard: http://localhost:${DEVMIN_WEB_PORT:-5000}
  - Config console: http://localhost:${DEVMIN_CONSOLE_PORT:-5002}
  - Bridge API: http://localhost:${DEVMIN_BRIDGE_PORT:-5001}
- **JP:** ブラウザで上記 URL にアクセスするとリアルタイム可視化や設定下発を確認できます。MQTT ブリッジ (port 5001) へ REST でアクセスすることも可能です。
- **CN:** 这些页面需在 devmin 容器运行时访问；控制台会读取 `data_receive.py` 上报的设备映射，以列出 DN/IP 并发送配置指令。

---

## 6. Stop / cleanup / 停止 / 停止

```bash
docker compose -f devmin/docker-compose.yml down
```
- **EN:** Collector script stops with `Ctrl+C`.
- **JP:** 収集停止後 `sink` が自動で CSV を閉じます。
- **CN:** 可按需删除 `devmin/data/mqtt_store` 中旧数据，或通过 Git 忽略保持本地数据不提交。
