#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import socket
import sys
import time
import base64

DEFAULT_PORT = 22345
DISCOVER_PORT = 22346
DISCOVER_MAGIC = "GCU_DISCOVER"


def send_json(host, port, payload):
  data = json.dumps(payload) + "\n"
  with socket.create_connection((host, port), timeout=5) as sock:
    sock.sendall(data.encode("utf-8"))
    chunks = []
    sock.settimeout(5)
    try:
      while True:
        resp = sock.recv(4096)
        if not resp:
          break
        chunks.append(resp)
    except socket.timeout:
      pass
    if not chunks:
      try:
        resp = sock.recv(4096)
        if resp:
          chunks.append(resp)
      except OSError:
        pass
    return b"".join(chunks).decode("utf-8", errors="ignore")


def discover_devices(broadcast_addr=None, attempts=1, gap=0.1, timeout=10.0):
  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
  sock.settimeout(timeout)
  sock.bind(("", 0))
  try:
    dest = (broadcast_addr or "255.255.255.255", DISCOVER_PORT)
    for i in range(max(1, attempts)):
      try:
        sock.sendto(DISCOVER_MAGIC.encode(), dest)
      except OSError:
        pass
      if gap > 0 and i + 1 < attempts:
        time.sleep(gap)
    results = []
    seen = set()
    while True:
      try:
        data, addr = sock.recvfrom(1024)
      except socket.timeout:
        break
      try:
        obj = json.loads(data.decode(errors="ignore"))
        obj["from"] = addr[0]
        sig = (obj.get("ip"), obj.get("mac"), obj.get("model"), obj.get("port"))
        if sig in seen:
          continue
        seen.add(sig)
        results.append(obj)
      except Exception:
        continue
    return results
  finally:
    sock.close()


def prompt_filter_config():
  en_str = input("是否启用滤波 [y/n/空跳过]: ").strip().lower()
  enabled = None
  if en_str in ("y", "yes", "1", "true"):
    enabled = True
  elif en_str in ("n", "no", "0", "false"):
    enabled = False
  alpha = input("IIR alpha (0.05~0.6，空跳过): ").strip()
  alpha_val = float(alpha) if alpha else None
  median = input("中值窗口 1/3/5 (空跳过): ").strip()
  median_val = int(median) if median else None
  payload = {"filter": {}}
  if enabled is not None:
    payload["filter"]["enabled"] = enabled
  if alpha_val is not None:
    payload["filter"]["alpha"] = alpha_val
  if median_val is not None:
    payload["filter"]["median"] = median_val
  return payload


def prompt_calibration_calibrate():
  analogpin = input("AnalogPin: ").strip()
  selectpin = input("SelectPin: ").strip()
  level = input("标定点值(level): ").strip()
  start_time = input("开始前等待(ms，默认1000): ").strip() or "1000"
  calib_time = input("采集时长(ms，默认5000): ").strip() or "5000"
  payload = {
    "calibration": {
      "command": "calibration",
      "analogpin": int(analogpin),
      "selectpin": int(selectpin),
      "level": float(level),
      "start_time": int(start_time),
      "calibration_time": int(calib_time)
    }
  }
  return payload


def main():
  bcast = input("广播地址(回车默认 255.255.255.255，可填网段广播如 192.168.1.255): ").strip() or None
  tries = input("广播次数(回车默认 1): ").strip()
  try:
    attempts = int(tries) if tries else 1
  except ValueError:
    attempts = 1
  print(f"正在广播到 {bcast or '255.255.255.255'}:{DISCOVER_PORT} ，共 {attempts} 次...")
  devices = discover_devices(broadcast_addr=bcast, attempts=attempts, gap=0.2)
  if devices:
    print("发现的设备：")
    for i, dev in enumerate(devices, 1):
      print(f"{i}. ip={dev.get('ip')} mac={dev.get('mac')} model={dev.get('model')} license={dev.get('license')} port={dev.get('port')}")
  else:
    print("未收到设备响应，可手动输入 IP 继续。")

  selection = input("选择设备序号，或直接输入 IP（留空退出）: ").strip()
  if not selection:
    return

  host = None
  port = DEFAULT_PORT
  if selection.isdigit() and devices:
    idx = int(selection)
    if 1 <= idx <= len(devices):
      host = devices[idx - 1].get("ip")
      port = int(devices[idx - 1].get("port") or DEFAULT_PORT)
  if host is None:
    host = selection
    port_in = input(f"端口 [默认 {DEFAULT_PORT}]: ").strip()
    port = int(port_in) if port_in else DEFAULT_PORT

  while True:
    print("【提示】校准、滤波配置和 SPIFFS 操作需在待机模式下(1 进入，2 退出)")
    print("1) 进入待机模式(standby enable)")
    print("2) 退出待机模式(standby disable)")
    print("3) 查询滤波配置")
    print("4) 设置滤波配置")
    print("5) 校准启用/关闭")
    print("6) 校准采集(calibration)")
    print("7) 查询校准状态(?)")
    print("8) 查询某标定 level 矩阵")
    print("9) 删除某标定 level")
    print("10) SPIFFS 列表")
    print("11) SPIFFS 读取到本地")
    print("12) SPIFFS 上传文件")
    print("13) SPIFFS 删除文件")
    print("0) 退出")
    action = input("选择 0-13: ").strip() or "3"

    if action == "0":
      break

    if action == "1":
      payload = {"standby": {"command": "enable"}}
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "2":
      payload = {"standby": {"command": "disable"}}
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "3":
      resp = send_json(host, port, {"filter": "?"})
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "4":
      payload = prompt_filter_config()
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "5":
      status = input("输入 enabled/disabled: ").strip().lower()
      payload = {"calibration": {"command": status}}
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "6":
      payload = prompt_calibration_calibrate()
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "7":
      payload = {"calibration": {"command": "?"}}
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "8":
      level = input("标定 level (如 0.5): ").strip()
      payload = {"calibration": {"command": "level", "level": level}}
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "9":
      level = input("标定 level (如 0.5): ").strip()
      payload = {"calibration": {"command": "delete", "level": level}}
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "10":
      payload = {"spiffs": {"command": "list"}}
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "11":
      remote = input("远端路径(如 /calib_0.00.csv): ").strip() or "/"
      limit = input("读取限制字节数(空=默认4096): ").strip()
      payload = {"spiffs": {"command": "read", "path": remote}}
      if limit:
        try:
          payload["spiffs"]["limit"] = int(limit)
        except ValueError:
          pass
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      if resp.strip().startswith("{") and "\"data_base64\"" in resp:
        try:
          obj = json.loads(resp)
          data_b64 = obj.get("data_base64", "")
          data = base64.b64decode(data_b64.encode())
          out_path = input("保存到本地文件路径(空=保存到当前目录同名文件): ").strip()
          if not out_path:
            fname = remote.split("/")[-1] or "spiffs.bin"
            out_path = fname
          with open(out_path, "wb") as f:
            f.write(data)
          print(f"已保存 {len(data)} 字节到 {out_path}")
        except Exception as e:
          print(f"解析/保存失败: {e}")
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "12":
      local_path = input("本地文件路径: ").strip()
      remote = input("远端路径(空=与本地同名): ").strip()
      if not remote:
        remote = "/" + local_path.split("\\")[-1].split("/")[-1]
        if not remote.startswith("/"):
          remote = "/" + remote
      try:
        with open(local_path, "rb") as f:
          data = f.read()
      except OSError as e:
        print(f"读取本地文件失败: {e}")
        input("按回车返回菜单...")
        continue
      b64 = base64.b64encode(data).decode()
      payload = {"spiffs": {"command": "write", "path": remote, "data_base64": b64}}
      resp = send_json(host, port, payload)
      print(f"发送: 写入 {len(data)} 字节到 {remote}")
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    if action == "13":
      remote = input("远端路径: ").strip()
      payload = {"spiffs": {"command": "delete", "path": remote}}
      resp = send_json(host, port, payload)
      print("发送:", json.dumps(payload))
      print("设备响应:", resp.strip() or "<空>")
      input("按回车返回菜单...")
      continue

    print("不支持的选项")


if __name__ == "__main__":
  main()
