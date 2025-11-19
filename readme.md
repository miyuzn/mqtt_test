# Devmin Guide (English)

> Developer-focused instructions for running the minimal parser + sink + web stack and collecting sensor data locally.

## 1. Clone & prerequisites
1. `git clone https://github.com/miyuzn/mqtt_test.git && cd mqtt_test`
2. Install Docker Desktop (Engine + Compose) and Python 3.11.
3. Verify:
   ```bash
   docker --version
   docker compose version
   python --version
   ```

## 2. Launch devmin containers
1. (Optional) `cp devmin/.env.example devmin/.env` and adjust ports if needed.
2. Start parser + sink + web:
   ```bash
   docker compose -f devmin/docker-compose.yml up -d --build
   ```
3. Inspect logs:
   ```bash
   docker compose -f devmin/docker-compose.yml logs -f parser sink web
   ```

## 3. Run local collector
1. Prepare virtual environment (first time only):
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r app/requirements.txt
   ```
2. Start collector (uses `devmin/config/data_receive.dev.ini`, connects to `127.0.0.1:1883`):
   ```bash
   python devmin/data_receive_local.py
   ```
3. `Ctrl+C` stops collection; CSV outputs appear under `devmin/data/mqtt_store/<DN>/<YYYYMMDD>/`.

## 4. Verify data
- Tail CSV files or monitor sink logs:
  ```bash
  docker compose -f devmin/docker-compose.yml logs -f sink
  ```
- Ensure `data_receive_local.py` prints incoming packets; check `devmin/data/mqtt_store` for per-DN folders.

## 5. Frontend & console (optional)
- Dashboard: `http://localhost:5000`
- Config console: `http://localhost:5002`

The console lists DN/IP mappings reported by collector instances and allows sending configuration commands.

## 6. Stop / cleanup
```bash
docker compose -f devmin/docker-compose.yml down
```
- Collector exits via `Ctrl+C`.
- Remove `devmin/data/mqtt_store` if you want to clear stored data.

---

# Devmin ガイド（日本語）

> 開発者向け。parser + sink + web の最小構成を起動し、ローカルでセンサデータを取得するまでの手順です。

## 1. クローンと前提環境
1. `git clone https://github.com/miyuzn/mqtt_test.git && cd mqtt_test`
2. Docker Desktop（Engine + Compose）と Python 3.11 をインストール。
3. 下記を実行して確認：
   ```bash
   docker --version
   docker compose version
   python --version
   ```

## 2. devmin コンテナ起動
1. 必要に応じ `cp devmin/.env.example devmin/.env` でポート設定を変更。
2. parser + sink + web を起動：
   ```bash
   docker compose -f devmin/docker-compose.yml up -d --build
   ```
3. ログ確認：
   ```bash
   docker compose -f devmin/docker-compose.yml logs -f parser sink web
   ```

## 3. ローカル収集プロセス
1. 初回のみ仮想環境を作成：
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r app/requirements.txt
   ```
2. `python devmin/data_receive_local.py` を実行すると収集開始。`CONFIG_PATH` は `devmin/config/data_receive.dev.ini`、MQTT は `127.0.0.1:1883` へ接続。
3. `Ctrl+C` で停止すると、CSV が `devmin/data/mqtt_store/<DN>/<YYYYMMDD>/` に保存されます。

## 4. 受信確認
- `docker compose -f devmin/docker-compose.yml logs -f sink` で `[MQTT] connected` や `[STATS] rows_written=...` を確認。
- `devmin/data/mqtt_store` に DN ごとのフォルダが生成されているかチェック。

## 5. フロントエンド/コンソール（任意）
- ダッシュボード: `http://localhost:5000`
- 設定コンソール: `http://localhost:5002`

設定コンソールでは collector が報告する DN/IP リストを基にコマンドを送信できます。

## 6. 停止
```bash
docker compose -f devmin/docker-compose.yml down
```
- 収集スクリプトは `Ctrl+C` で終了。
- 必要に応じ `devmin/data/mqtt_store` を削除し、データをリセットします。

---

# Devmin 指南（中文）

> 面向开发者的说明：使用 devmin（parser + sink + web）最小栈，在本地快速收取传感器数据。

## 1. 克隆与准备
1. `git clone https://github.com/miyuzn/mqtt_test.git && cd mqtt_test`
2. 安装 Docker Desktop（Engine + Compose）与 Python 3.11。
3. 验证：
   ```bash
   docker --version
   docker compose version
   python --version
   ```

## 2. 启动 devmin 容器
1. 可选：`cp devmin/.env.example devmin/.env` 并调整端口。
2. 启动 parser + sink + web：
   ```bash
   docker compose -f devmin/docker-compose.yml up -d --build
   ```
3. 查看日志：
   ```bash
   docker compose -f devmin/docker-compose.yml logs -f parser sink web
   ```

## 3. 本地采集
1. 首次执行需创建虚拟环境：
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r app/requirements.txt
   ```
2. 运行 `python devmin/data_receive_local.py`，自动使用 `devmin/config/data_receive.dev.ini`，并连接本机 `127.0.0.1:1883`。
3. `Ctrl+C` 结束采集；CSV 会写入 `devmin/data/mqtt_store/<DN>/<YYYYMMDD>/`。

## 4. 数据校验
- `docker compose -f devmin/docker-compose.yml logs -f sink` 可查看写入状态。
- 检查 `devmin/data/mqtt_store` 中是否出现对应 DN 的 CSV 文件。

## 5. 前端与控制台（可选）
- 仪表盘: `http://localhost:5000`
- 配置控制台: `http://localhost:5002`

控制台会根据 `data_receive.py` 上报的 DN/IP 映射发送配置指令。

## 6. 停止与清理
```bash
docker compose -f devmin/docker-compose.yml down
```
- 采集脚本通过 `Ctrl+C` 退出。
- 可随时清理 `devmin/data/mqtt_store`，避免旧数据占用空间。
