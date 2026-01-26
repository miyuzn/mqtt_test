# MQTT Sensor System & JSCMS 集成实施报告 (As-Built)

**更新日期:** 2026-01-26
**状态:** 已完成 (Implemented)

## 1. 总体架构：职责分离 (Separation of Concerns)

为了规避 Legacy Java 系统的维护风险并提升性能，采用了**“物理分离，数据共享”**的架构模式。

*   **普通用户通道 (User Portal)**: `mqtt-web` 容器 (Port 5000/443)。
    *   全业务流程闭环：登录、实时监控、历史文件查询、批量下载。
    *   技术栈：Python Flask + Gevent + Jinja2 (前端移植)。
*   **管理员通道 (Admin Console)**: `jscms-container` (Port 8080)。
    *   仅用于后台元数据管理（用户、组、设备注册）。
*   **数据层 (Shared Truth)**: PostgreSQL。
    *   作为两个系统的唯一数据交接点。

## 2. 核心功能实现

### A. 身份认证 (Authentication)
*   **登录**: Flask 实现 `/login` 路由。
    *   直接校验 PostgreSQL `app_user` 表（目前支持明文密码）。
*   **Session**:
    *   使用 Flask Signed Cookie，独立于 Java Session。
    *   配置了 30 分钟自动超时，前端实现了倒计时和手动续期功能。
*   **Admin 特权**:
    *   用户 `admin` 登录后，跳过设备白名单过滤，可查看 MQTT 发现的所有设备（包括未注册设备）。

### B. 数据与权限控制 (Authorization)
*   **权限模型**: `User -> UserGroup -> DeviceInfo`。
*   **Dashboard 过滤**:
    *   后端查询 DB 获取 `allowed_dns`。
    *   前端 JS (`index.html`) 在数据接收层 (`applyEntry`) 实施白名单过滤，确保未授权设备不渲染。
*   **实时流 (SSE)**:
    *   **性能优化**: 后端采用 `iter_content` 纯字节透传，避免了 Python 逐行解析 JSON 导致的 CPU 瓶颈。过滤压力下放至前端。
*   **文件下载**:
    *   后端路由 `/download/<path>` 强制检查目标 MAC 是否属于用户权限范围。

### C. 文件管理 (Data Management)
*   **实时入库**: `sink.py` 在 CSV 文件创建和关闭时，自动向 `data_files` 表插入/更新记录（Size, Timestamp）。
*   **全量索引重建**:
    *   `sink` 容器启动时（及每 24h）自动执行全盘扫描。
    *   **策略**: `TRUNCATE` + `INSERT`，确保数据库完全镜像磁盘状态，清除僵尸记录。
    *   **鲁棒性**: 递归扫描，忽略非标准目录结构；优先读取 CSV 内容获取精准时间戳；自动过滤无效 MAC 以满足外键约束。
*   **批量下载**:
    *   新增 `/download/batch` 接口，支持多选文件打包为 ZIP 下载。
    *   前端 `downloads.html` 改造为 Device -> Date -> Files 三级导航，提升易用性。

## 3. 部署配置 (Docker)

*   **容器编排**:
    *   `web` 和 `sink` 容器注入了 `DB_HOST`, `DB_USER` 等环境变量。
    *   `web` 容器只读挂载 (`:ro`) 了 `backend/mqtt_store`，实现了文件下载能力。
*   **依赖库**:
    *   `web` 和 `backend` 均已安装 `psycopg2-binary`。

## 4. 遗留问题与规避

*   **Java 后台 Bug**: JSCMS 的设备新增功能存在表单验证 Bug。
    *   **规避**: 提供了 Python 脚本 `force_register_devices.py`，可自动扫描磁盘并将所有设备注册到数据库。
*   **Timeout 误报**: Config Console (:5002) 偶发 `timed out` 错误。
    *   **原因**: 主要是设备未在线或未回复 Discovery。
    *   **优化**: 已将发现超时时间从 5s 延长至 10s。

## 5. 后续维护指南

*   **重启服务**: 修改 Python 代码后，需重启对应容器 (`docker restart mqtt-web` 或 `mqtt-sink`)。
*   **数据一致性**: 若发现文件列表不准，可重启 `mqtt-sink` 触发立即重扫描。
*   **新设备注册**: 推荐使用 `python force_register_devices.py` 快速入库。
