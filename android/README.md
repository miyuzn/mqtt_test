# Android 端数据桥路线图 / Android Bridge Plan

## 背景 / Context
- 现有 `data_receive.py` 在 PC 端通过 UDP 监听传感器广播，解析后再以 MQTT（Paho）推送到桥接/topic；
- 终端用户若无法部署 PC，可在 Android 设备上实现同等逻辑：UDP 收包 → 解析 → MQTT 发布，并支持配置/状态上报；
- Android 需兼顾前台可视化与后台长连接，需注意系统节电策略与权限。

## 推荐实现路线 / Suggested Approach
1. **技术栈**  
   - Kotlin + Android Jetpack（WorkManager / Foreground Service）实现常驻任务；  
   - 使用 `java.net.DatagramSocket`/`DatagramChannel` 监听 UDP；  
   - 解析层可移植 `sensor2.py` 逻辑到 Kotlin（或以 JNI 复用 Python/ C，但 Kotlin 重写更轻量）；  
   - MQTT 推荐使用 Eclipse Paho Android Service 或 HiveMQ MQTT Client。
2. **架构分层**  
   - `core-network`: UDP 接收、MQTT 发布、重连/退避；  
   - `parser`: DN/SN/压力等字段解析与镜像；  
   - `repository`: 缓存最近帧、维持设备注册表；  
   - `ui`: 简易状态页（连接指示、活跃设备列表）；  
   - `config`: 读取本地 `SharedPreferences`/`datastore`，可支持 QR/JSON 导入。
3. **运行模式**  
   - 前台：展示状态并允许用户切换 MQTT/UDP 目标；  
   - 后台：Foreground Service + Notification，保持 UDP/MQTT 长连；  
   - 可选使用 WorkManager 周期性同步配置或上报设备清单。
4. **关键注意事项**  
   - Android 13+ 需要 `POST_NOTIFICATIONS` 权限以保持前台服务；  
   - Wi-Fi 广播/组播权限（`CHANGE_WIFI_MULTICAST_STATE`）若设备使用局域网广播；  
   - 需处理移动网络下的 UDP 限制，可提供手动输入远端 IP 模式；  
   - MQTT 证书与凭据需安全存储（Keystore / EncryptedSharedPreferences）。

## 目录规划 / Directory Layout
```
android/
  README.md              ← 本说明
  app/                   ← 后续可放置 Android Studio 工程
    build.gradle
    src/main/java/...
  parser/                ← 若将 sensor2 解析独立模块，可放于此
```

## 下一步 / Next Steps
1. 在 `android/app` 下初始化 Android Studio 项目（Kotlin）；  
2. 迁移/重写 `sensor2` 解析逻辑，并以 JVM 单元测试验证；  
3. 实现 UDP → Channel → MQTT 管道，参考 `data_receive.py` 的队列与重连策略；  
4. 打通配置界面与前台通知，确保在后台保持运行；  
5. 与现有后端联调，验证 MQTT 主题/负载兼容性。

> 说明：此 README 仅定义开发路线与结构，实际代码可在后续 PR 中补充。 We keep this file bilingual for wider collaboration.
