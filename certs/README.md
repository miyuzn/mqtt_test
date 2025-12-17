# 本地自签证书（开发/联调）

该目录用于存放本地自签 CA 与服务端证书（仅用于联调/验证 TLS 链路），不要提交私钥到仓库。

## 生成（Windows PowerShell）

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev_generate_certs.ps1 -Force
```

生成结果（默认）：
- `certs/ca.crt`、`certs/ca.key`：本地 CA（`ca.key` 请勿外发）
- `certs/mosquitto.crt`、`certs/mosquitto.key`：MQTTS(8883) 服务端证书
- `certs/web.crt`、`certs/web.key`：HTTPS(443) 服务端证书

默认 SAN 已包含内网调试地址 `163.143.136.106`（如需替换为其它 IP，可在脚本参数 `-MosquittoIpAddresses/-WebIpAddresses` 指定）。

## 信任（可选）

浏览器/客户端若需消除“自签不受信任”的提示，可将 `certs/ca.crt` 导入到系统/浏览器的受信任根证书。

Windows 下 `curl.exe` 可能会因为证书吊销检查返回 `CERT_TRUST_REVOCATION_STATUS_UNKNOWN`，可改用：

```powershell
curl.exe --ssl-no-revoke --cacert certs\ca.crt https://163.143.136.106/healthz
```

若仍提示证书不受信任（Windows `curl.exe` 默认使用 Schannel，可能不会按预期使用 `--cacert`），建议二选一：

1) 将 `certs/ca.crt` 导入 “受信任的根证书颁发机构”，再访问 `https://163.143.136.106/`
2) 仅联调临时跳过校验：`curl.exe -k https://163.143.136.106/healthz`
