# MQTT Sensor System & JSCMS 架构重构计划 (2026-01-23 最终执行版)

## 1. 核心策略：彻底分离 (Complete Separation)
*   **普通用户通道**: 直接访问 `mqtt-web` 容器 (Port 5000/443)。全业务流程（登录、监控、下载）均在此容器内完成。
*   **管理员通道**: 直接访问 `jscms-container` (Port 8080)。仅用于后台管理。
*   **网关策略**: 移除 Nginx，利用端口隔离。

## 2. 详细技术方案 (Python 侧实现)

### A. 身份认证 (Authentication)
*   **登录**: Flask 实现 `/login`。直接校验 PostgreSQL `app_user` 表中的明文密码。
*   **登出**: Flask 实现 `/logout` (清除 Session)。
*   **Session**: 使用 Flask Signed Cookie。配置 `PERMANENT_SESSION_LIFETIME = 30分钟`。

### B. 用户权限逻辑设计 (User Permission Design)
*   **数据源**: PostgreSQL (`app_user` -> `user_group` -> `device_info`)。
*   **逻辑层 (`web/db_manager.py`)**:
    1.  `authenticate_user(username, password)`: 验证账号密码。
    2.  `get_user_allowed_devices(user_id)`: 返回用户可访问的设备列表。
        *   **特例规则**: 如果用户名为 `admin`，则直接返回**所有**设备 (SELECT * FROM device_info)，跳过组关联检查。这用于系统调试和全局监控。
    3.  `log_file_generation(...)`: Sink 用于记录文件信息。
*   **业务层集成**:
    *   **Dashboard**: 获取允许设备列表 -> 传给模板 -> 前端只渲染对应卡片。
    *   **SSE Stream**: 在 Python 端拦截数据流，仅推送 `dn` 在允许列表中的数据帧。
    *   **Download**: 仅允许下载路径中包含允许 MAC 地址的文件。

### C. 文件管理 (Data Management)
*   **写入 (Sink)**: `sink.py` 在创建新 CSV 时，执行 `INSERT INTO data_files`。
*   **下载 (Web)**: 移植 `dataFiles.jsp` -> `downloads.html` (Jinja2)。
*   **流式下载**: 使用 `flask.send_from_directory`。

## 3. 实施步骤清单

### Phase 1: 基础设施 (配置)
1.  **依赖**: `web` 和 `backend` 安装 `psycopg2-binary`。
2.  **配置**: `docker-compose.secure.yml` 传入 DB 连接信息。

### Phase 2: 核心代码 (Python)
3.  **DB Manager**: 创建 `web/db_manager.py` (含 Admin 特权逻辑)。
4.  **Sink 升级**: 修改 `sink.py` 对接 DB。
5.  **Web 升级**: 修改 `app.py`。
    *   增加 `SECRET_KEY`。
    *   增加 Auth 路由 (`/login`, `/logout`)。
    *   增加 Download 路由。
    *   修改 Stream 路由支持权限过滤。

### Phase 3: 前端移植
6.  **页面**: 创建 `login.html` 和 `downloads.html`。
7.  **导航**: 修改 `index.html` 增加菜单。

### Phase 4: 上线验证
8.  重启服务并测试 `admin` 及普通用户权限。