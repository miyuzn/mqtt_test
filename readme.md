英語の下に日本語訳があります。
中文翻译在英文、日文下方。

# Devmin Guide
> Local minimal ESP32 data pipeline: ingest -> process -> store -> visualize.

## Quick overview
- Goal: run a G-CU 4.1+ ESP32 locally with MQTT + sink + web UI for data capture.
- Data path: `./devmin/data/mqtt_store/<Device_DN>/<Date>/<exp_time>.csv`
- Data dashboard: http://localhost:5000
- Config console: http://localhost:5002

## Hardware
- Use an ESP32 running G-CU firmware v4.1.1 or newer (https://github.com/Preston-Yu/G-CU/tree/main/Arduino/v4.1.1).
- First-time devices need a License Key push from the config console; pick the correct device, license type, and activation window to get normal packet rates.

## Network
- Keep the ESP32 and the collector PC on the same WiFi network.
- Provision WiFi with the "ESP BLE Prov" mobile app; power-cycle or reset the ESP32 five times to enter provisioning mode.

## Local environment
### Prereqs and notes
- Windows: ensure `devmin/scripts/parser_entry.sh`, `sink_entry.sh`, and `webstack_entry.sh` use LF line endings; if containers refuse to start, also check all `.sh` under `devmin/scripts/` for LF endings.
- Copy `nas/Public/ESP32/priv.pem` into `license/priv.pem` where required.
- Tools: WSL updated, Docker Desktop (Engine + Compose), Python 3.11, `paho-mqtt`.

### Clone and setup
```bash
git clone https://github.com/miyuzn/mqtt_test.git
cd mqtt_test
wsl --update    # Windows only
pip install paho-mqtt
```

### First-time container stack
```bash
docker compose -f devmin/docker-compose.yml up -d --build
```
> Do not run compose files in the repo root; those YAMLs are for debugging.

### Run the local collector
```bash
python devmin/data_receive_local.py
```
- Uses `devmin/config/data_receive.dev.ini`, connects to `127.0.0.1:1883`.
- Stop with `Ctrl+C`; CSV output goes to `devmin/data/mqtt_store/<DN>/<YYYYMMDD>/<exp_time>.csv`.

### Verify data flow
- Check sink logs:
```bash
docker compose -f devmin/docker-compose.yml logs -f sink
```
- Confirm `data_receive_local.py` prints packets; check per-DN CSVs under `devmin/data/mqtt_store`.

## Access points
- Data dashboard: http://localhost:5000
- Config console: http://localhost:5002 (shows DN/IP mappings and sends config/license commands)

## Daily data collection
1. Start the prebuilt devmin containers (all 3 services) without rebuilding:
   ```bash
   docker compose -f devmin/docker-compose.yml up -d
   ```
2. Start the data collection script:
   ```bash
   python devmin/data_receive_local.py
   ```
   Do not swap steps 1/2; starting the script first will fail because MQTT inside the containers is not ready.
3. During collection, view live data at http://localhost:5000.
4. To stop collection, end the data collection script (all devices stop together) or cut power to a specific ESP32. If it does not reconnect within 5 seconds, the current data is flushed into the storage path with the filename set to the collection start timestamp.

## Troubleshooting
- If provisioning is needed again, power-cycle the ESP32 five times to enter WiFi setup.
- On Windows Docker builds, ensure all three `.sh` files under `devmin/scripts/` are LF-terminated if containers fail to start.

---

## 日本語訳

# Devmin ガイド

> ローカル最小構成の ESP32 データパイプライン: 取り込み -> 処理 -> 保存 -> 可視化。

## クイック概要
- 目的: MQTT + シンク + Web UI を使い、G-CU 4.1+ ESP32 をローカルで動かしデータを取得。
- データ保存先: `./devmin/data/mqtt_store/<Device_DN>/<Date>/<exp_time>.csv`
- ダッシュボード: http://localhost:5000
- 設定コンソール: http://localhost:5002

## ハードウェア
- G-CU ファームウェア v4.1.1 以上を動かす ESP32 を使用 https://github.com/Preston-Yu/G-CU/tree/main/Arduino/v4.1.1
- 初回利用デバイスは設定コンソールからライセンスキーをプッシュする必要あり。正しいデバイス・ライセンスタイプ・有効期間を選び通常のパケットレートを得る。

## ネットワーク
- ESP32 と収集用 PC を同じ WiFi に接続。
- "ESP BLE Prov" モバイルアプリで WiFi を設定。ESP32 を 5 回再起動またはリセットしてプロビジョニングモードに入る。

## ローカル環境
### 前提と注意
- Windows: `devmin/scripts/parser_entry.sh`、`sink_entry.sh`、`webstack_entry.sh` は LF 改行にする。コンテナが起動しない場合は `devmin/scripts/` 配下の `.sh` も LF か確認。
- `nas/Public/ESP32/priv.pem` を必要な場所の `license/priv.pem` にコピー。
- ツール: WSL 最新、Docker Desktop (Engine + Compose)、Python 3.11、`paho-mqtt`。

### クローンとセットアップ
```bash
git clone https://github.com/miyuzn/mqtt_test.git
cd mqtt_test
wsl --update    # Windows のみ
pip install paho-mqtt
```

### 初回のコンテナスタック
```bash
docker compose -f devmin/docker-compose.yml up -d --build
```
> リポジトリルートの compose ファイルはデバッグ用なので実行しないこと。

### ローカルコレクターを実行
```bash
python devmin/data_receive_local.py
```
- `devmin/config/data_receive.dev.ini` を使用し、`127.0.0.1:1883` に接続。
- `Ctrl+C` で停止。CSV は `devmin/data/mqtt_store/<DN>/<YYYYMMDD>/<exp_time>.csv` に出力。

### データフローを確認
- シンクログを確認:
```bash
docker compose -f devmin/docker-compose.yml logs -f sink
```
- `data_receive_local.py` がパケットを出力することを確認。`devmin/data/mqtt_store` 配下の DN ごとの CSV を確認。

## アクセスポイント
- ダッシュボード: http://localhost:5000
- 設定コンソール: http://localhost:5002 (DN/IP マッピング表示、設定/ライセンスコマンド送信)

## 日常的なデータ収集
1. ビルドなしで事前構築済み devmin コンテナ (3 サービス) を起動:
   ```bash
   docker compose -f devmin/docker-compose.yml up -d
   ```
2. データ収集スクリプトを起動:
   ```bash
   python devmin/data_receive_local.py
   ```
   手順 1/2 を入れ替えないこと。先にスクリプトを起動すると、コンテナ内 MQTT が未準備で失敗する。
3. 収集中は http://localhost:5000 でライブデータを閲覧。
4. 収集停止はスクリプトを終了 (全デバイス同時停止) するか、特定 ESP32 の電源を切る。5 秒以内に再接続しない場合、現在のデータがストレージパスに保存され、ファイル名は収集開始時刻となる。

## トラブルシューティング
- 再プロビジョニングが必要な場合、ESP32 を 5 回再起動して WiFi セットアップに入る。
- Windows での Docker ビルド時、コンテナが起動しない場合は `devmin/scripts/` 配下の 3 つの `.sh` が LF 終端か確認。

---

## 中文翻译

# Devmin 指南

> 本地最小 ESP32 数据管线：采集 -> 处理 -> 存储 -> 可视化。

## 快速概览
- 目标：用 MQTT + sink + Web UI 在本地运行 G-CU 4.1+ ESP32 进行数据采集。
- 数据路径：`./devmin/data/mqtt_store/<Device_DN>/<Date>/<exp_time>.csv`
- 数据看板：http://localhost:5000
- 配置控制台：http://localhost:5002

## 硬件
- 使用运行 G-CU 固件 v4.1.1 或更高版本的 ESP32 https://github.com/Preston-Yu/G-CU/tree/main/Arduino/v4.1.1
- 首次设备需要在配置控制台推送 License Key；选择正确的设备、许可类型和有效期以获得正常的包速率。

## 网络
- 让 ESP32 与采集 PC 处于同一 WiFi。
- 用 "ESP BLE Prov" 手机应用配置 WiFi；给 ESP32 断电或复位 5 次进入配网模式。

## 本地环境
### 前置条件与注意
- Windows：确保 `devmin/scripts/parser_entry.sh`、`sink_entry.sh`、`webstack_entry.sh` 使用 LF 换行；若容器无法启动，也检查 `devmin/scripts/` 下所有 `.sh` 是否为 LF。
- 将 `nas/Public/ESP32/priv.pem` 复制到需要位置的 `license/priv.pem`。
- 工具：WSL 更新、Docker Desktop (Engine + Compose)、Python 3.11、`paho-mqtt`。

### 克隆与设置
```bash
git clone https://github.com/miyuzn/mqtt_test.git
cd mqtt_test
wsl --update    # 仅 Windows
pip install paho-mqtt
```

### 首次容器栈
```bash
docker compose -f devmin/docker-compose.yml up -d --build
```
> 不要运行仓库根目录的 compose 文件；那些 YAML 仅用于调试。

### 运行本地采集器
```bash
python devmin/data_receive_local.py
```
- 使用 `devmin/config/data_receive.dev.ini`，连接 `127.0.0.1:1883`。
- 按 `Ctrl+C` 停止；CSV 输出到 `devmin/data/mqtt_store/<DN>/<YYYYMMDD>/<exp_time>.csv`。

### 验证数据流
- 查看 sink 日志：
```bash
docker compose -f devmin/docker-compose.yml logs -f sink
```
- 确认 `data_receive_local.py` 打印数据包；检查 `devmin/data/mqtt_store` 下按 DN 存放的 CSV。

## 访问入口
- 数据看板：http://localhost:5000
- 配置控制台：http://localhost:5002（显示 DN/IP 映射并发送配置/许可指令）

## 日常数据采集
1. 无需重建，启动预构建的 devmin 容器（3 个服务）：
   ```bash
   docker compose -f devmin/docker-compose.yml up -d
   ```
2. 启动数据采集脚本：
   ```bash
   python devmin/data_receive_local.py
   ```
   不要调换 1/2 步骤；先启动脚本会因容器内 MQTT 未就绪而失败。
3. 采集过程中在 http://localhost:5000 查看实时数据。
4. 结束采集时结束脚本（所有设备同时停止）或切断某 ESP32 电源。若 5 秒内未重连，当前数据会写入存储路径，文件名为采集开始时间。

## 故障排查
- 若需要重新配网，将 ESP32 断电 5 次进入 WiFi 设置。
- Windows Docker 构建时，若容器无法启动，确认 `devmin/scripts/` 下 3 个 `.sh` 均为 LF 结束。
