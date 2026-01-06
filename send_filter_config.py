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


def parse_json_response(resp):
  text = resp.strip()
  if not text:
    return None
  try:
    return json.loads(text)
  except Exception:
    pass
  for line in text.splitlines():
    line = line.strip()
    if not line:
      continue
    if not (line.startswith("{") and line.endswith("}")):
      continue
    try:
      return json.loads(line)
    except Exception:
      continue
  return None


def reorder_log_bytes(data, offset):
  if not data:
    return data
  if offset <= 0 or offset >= len(data):
    return data.rstrip(b"\x00")
  tail = data[offset:]
  if any(b != 0 for b in tail):
    ordered = tail + data[:offset]
  else:
    ordered = data[:offset]
  return ordered.strip(b"\x00")


def prompt_filter_config():
  en_str = input("Enable filter? [y/n/blank=skip]: ").strip().lower()
  enabled = None
  if en_str in ("y", "yes", "1", "true"):
    enabled = True
  elif en_str in ("n", "no", "0", "false"):
    enabled = False
  alpha = input("IIR alpha (0.05~0.6, blank=skip): ").strip()
  alpha_val = float(alpha) if alpha else None
  median = input("Median window 1/3/5 (blank=skip): ").strip()
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
  level = input("Calibration level value: ").strip()
  start_time = input("Start delay (ms, default 1000): ").strip() or "1000"
  calib_time = input("Sampling duration (ms, default 5000): ").strip() or "5000"
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


def prompt_calibration_all():
  level = input("Calibration level (default 0): ").strip() or "0"
  start_time = input("Start delay (ms, default 1000): ").strip() or "1000"
  calib_time = input("Sampling duration (ms, default 5000): ").strip() or "5000"
  payload = {
    "calibration": {
      "command": "calibrate_all",
      "level": float(level),
      "start_time": int(start_time),
      "calibration_time": int(calib_time)
    }
  }
  return payload


def main():
  bcast = input("Broadcast address (default 255.255.255.255, e.g. 192.168.1.255): ").strip() or None
  tries = input("Broadcast attempts (default 1): ").strip()
  try:
    attempts = int(tries) if tries else 1
  except ValueError:
    attempts = 1
  print(f"Broadcasting to {bcast or '255.255.255.255'}:{DISCOVER_PORT}, attempts={attempts} ...")
  devices = discover_devices(broadcast_addr=bcast, attempts=attempts, gap=0.2)
  if devices:
    print("Discovered devices:")
    for i, dev in enumerate(devices, 1):
      print(f"{i}. ip={dev.get('ip')} mac={dev.get('mac')} model={dev.get('model')} license={dev.get('license')} port={dev.get('port')}")
  else:
    print("No device responses; you can enter an IP manually.")

  selection = input("Select device index, or enter IP directly (blank to exit): ").strip()
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
    port_in = input(f"Port [default {DEFAULT_PORT}]: ").strip()
    port = int(port_in) if port_in else DEFAULT_PORT

  while True:
    print("[Note] Calibration/filter/SPIFFS/log operations require standby (1 enter, 2 exit).")
    print("[Note] Log enable will reboot the device.")
    print("1) Enter standby (enable)")
    print("2) Exit standby (disable)")
    print("3) Query filter config")
    print("4) Set filter config")
    print("5) Enable/disable calibration")
    print("6) Calibrate single sensor")
    print("7) Query calibration status (?)")
    print("8) Dump calibration matrix for a level")
    print("9) Delete a calibration level")
    print("10) SPIFFS list")
    print("11) SPIFFS read to local")
    print("12) SPIFFS upload file")
    print("13) SPIFFS delete file")
    print("14) Calibrate all sensors")
    print("15) Log status")
    print("16) Log enable")
    print("17) Log disable")
    print("18) Log download (ordered)")
    print("0) Exit")
    action = input("Choose 0-18: ").strip() or "3"

    if action == "0":
      break

    if action == "1":
      payload = {"standby": {"command": "enable"}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "2":
      payload = {"standby": {"command": "disable"}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "3":
      resp = send_json(host, port, {"filter": "?"})
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "4":
      payload = prompt_filter_config()
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "5":
      status = input("Enter enabled/disabled: ").strip().lower()
      payload = {"calibration": {"command": status}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "6":
      payload = prompt_calibration_calibrate()
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "7":
      payload = {"calibration": {"command": "?"}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "8":
      level = input("Calibration level (e.g. 0.5): ").strip()
      payload = {"calibration": {"command": "level", "level": level}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "9":
      level = input("Calibration level to delete (e.g. 0.5): ").strip()
      payload = {"calibration": {"command": "delete", "level": level}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "10":
      payload = {"spiffs": {"command": "list"}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "11":
      remote = input("Remote path (e.g. /calib_0.00.csv): ").strip() or "/"
      limit = input("Read limit bytes (blank=4096): ").strip()
      payload = {"spiffs": {"command": "read", "path": remote}}
      if limit:
        try:
          payload["spiffs"]["limit"] = int(limit)
        except ValueError:
          pass
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      if resp.strip().startswith("{") and "\"data_base64\"" in resp:
        try:
          obj = json.loads(resp)
          data_b64 = obj.get("data_base64", "")
          data = base64.b64decode(data_b64.encode())
          out_path = input("Save to local path (blank=use same name): ").strip()
          if not out_path:
            fname = remote.split("/")[-1] or "spiffs.bin"
            out_path = fname
          with open(out_path, "wb") as f:
            f.write(data)
          print(f"Saved {len(data)} bytes to {out_path}")
        except Exception as e:
          print(f"Parse/save failed: {e}")
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "12":
      local_path = input("Local file path: ").strip()
      remote = input("Remote path (blank=use local filename): ").strip()
      if not remote:
        remote = "/" + local_path.split("\\")[-1].split("/")[-1]
        if not remote.startswith("/"):
          remote = "/" + remote
      try:
        with open(local_path, "rb") as f:
          data = f.read()
      except OSError as e:
        print(f"Failed to read local file: {e}")
        input("Press Enter to return to menu...")
        continue
      b64 = base64.b64encode(data).decode()
      payload = {"spiffs": {"command": "write", "path": remote, "data_base64": b64}}
      resp = send_json(host, port, payload)
      print(f"Send: wrote {len(data)} bytes to {remote}")
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "13":
      remote = input("Remote path: ").strip()
      payload = {"spiffs": {"command": "delete", "path": remote}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "14":
      payload = prompt_calibration_all()
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "15":
      payload = {"log": {"command": "status"}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "16":
      level = input("Log level (debug/info/warn/error): ").strip().lower()
      if level not in ("debug", "info", "warn", "error"):
        print("Invalid level; expected debug/info/warn/error")
        input("Press Enter to return to menu...")
        continue
      payload = {"log": {"command": "enable", "level": level}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      print("Note: device will reboot if enabled.")
      input("Press Enter to return to menu...")
      continue

    if action == "17":
      payload = {"log": {"command": "disable"}}
      resp = send_json(host, port, payload)
      print("Send:", json.dumps(payload))
      print("Device response:", resp.strip() or "<empty>")
      input("Press Enter to return to menu...")
      continue

    if action == "18":
      status_resp = send_json(host, port, {"log": {"command": "status"}})
      status_obj = parse_json_response(status_resp) or {}
      log_obj = status_obj.get("log") if isinstance(status_obj, dict) else None
      offset = None
      max_bytes = None
      if isinstance(log_obj, dict):
        offset = log_obj.get("offset")
        max_bytes = log_obj.get("max_bytes")
      try:
        offset = int(offset) if offset is not None else None
      except (TypeError, ValueError):
        offset = None
      try:
        max_bytes = int(max_bytes) if max_bytes is not None else 32768
      except (TypeError, ValueError):
        max_bytes = 32768

      payload = {"spiffs": {"command": "read", "path": "/log.txt", "limit": max_bytes}}
      resp = send_json(host, port, payload)
      obj = parse_json_response(resp)
      if not obj or "data_base64" not in obj:
        print("Send:", json.dumps(payload))
        print("Device response:", resp.strip() or "<empty>")
        input("Press Enter to return to menu...")
        continue
      try:
        data = base64.b64decode(obj.get("data_base64", "").encode())
      except Exception as e:
        print(f"Decode failed: {e}")
        input("Press Enter to return to menu...")
        continue

      ordered = reorder_log_bytes(data, offset or 0)
      out_path = input("Save to local path (blank=log_ordered.txt): ").strip() or "log_ordered.txt"
      try:
        with open(out_path, "wb") as f:
          f.write(ordered)
        print(f"Saved {len(ordered)} bytes to {out_path}")
        if offset is not None:
          print(f"Used offset: {offset}")
      except OSError as e:
        print(f"Save failed: {e}")
      input("Press Enter to return to menu...")
      continue

    print("Unsupported option")


if __name__ == "__main__":
  main()
