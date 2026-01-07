import json
import os
import re
import hashlib
import time
import argparse
import sys
from collections import defaultdict
from urllib.parse import urlparse, urlunparse

# Configuration
OTA_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(OTA_DIR, "manifest.json")

# Regex to match: gcu-<model>-<version>.bin
# Handles optional 'v' prefix in version (e.g., v4.2.2 or 4.2.2)
# Example: gcu-22c-v4.2.2.bin -> model="22c", version="4.2.2"
FILENAME_PATTERN = re.compile(r"^gcu-(.+?)-v?(\d+(?:\.\d+)*)\.bin$", re.IGNORECASE)

def calculate_sha256(filepath):
    """Calculate the SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        # Read in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def parse_version(version_str):
    """Convert version string to tuple for semantic comparison (e.g. '4.2.10' > '4.2.9')."""
    return tuple(map(int, version_str.split(".")))

def get_base_url(current_manifest_path):
    """
    Determine the base URL (e.g., https://example.com/OTA/).
    Tries to read from existing manifest to preserve the domain configuration.
    Defaults to placeholder if not found.
    """
    default_base = "https://<YOUR_DOMAIN_OR_IP>/OTA/"
    
    if os.path.exists(current_manifest_path):
        try:
            with open(current_manifest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                devices = data.get("devices", [])
                if devices:
                    # Pick the URL from the first device to extract the base
                    first_url = devices[0].get("url", "")
                    if first_url:
                        parsed = urlparse(first_url)
                        # Reconstruct base: scheme://netloc/path_dir/
                        path_dir = os.path.dirname(parsed.path)
                        # Ensure path ends with / and doesn't duplicate OTA if present
                        if not path_dir.endswith("/"):
                            path_dir += "/"
                        
                        # Fix logic: simple replacement of filename
                        return urlunparse((parsed.scheme, parsed.netloc, path_dir, "", "", ""))
        except Exception:
            pass
    
    return default_base

def generate_manifest():
    """Scan directory, find latest versions, and rewrite manifest.json."""
    if not os.path.exists(OTA_DIR):
        print(f"[Error] OTA directory not found: {OTA_DIR}")
        return

    # 1. Scan files
    files = [f for f in os.listdir(OTA_DIR) if f.lower().endswith(".bin")]
    
    model_groups = defaultdict(list)
    
    for filename in files:
        match = FILENAME_PATTERN.match(filename)
        if match:
            model = match.group(1)
            version_str = match.group(2)
            full_path = os.path.join(OTA_DIR, filename)
            
            model_groups[model].append({
                "filename": filename,
                "version_str": version_str,
                "version_tuple": parse_version(version_str),
                "full_path": full_path
            })
    
    if not model_groups:
        print("[Info] No matching firmware files (gcu-<model>-<ver>.bin) found.")
        return

    # 2. Get Base URL
    base_url = get_base_url(MANIFEST_PATH)
    if not base_url.endswith("/"):
        base_url += "/"

    # 3. Build Device List
    devices_list = []
    print(f"[Info] Scanning {len(files)} files in {OTA_DIR}...")
    
    for model, items in model_groups.items():
        # Sort by version descending
        items.sort(key=lambda x: x["version_tuple"], reverse=True)
        latest = items[0]
        
        print(f"  - Model: {model} -> Latest: {latest['version_str']} ({latest['filename']})")
        
        # Calculate SHA256
        checksum = calculate_sha256(latest["full_path"])
        
        # Construct URL
        # Assuming base_url is "https://domain/OTA/" and filename is "file.bin"
        # Result: "https://domain/OTA/file.bin"
        download_url = f"{base_url}{latest['filename']}"
        
        devices_list.append({
            "model": model,
            "latest": latest["version_str"],
            "url": download_url,
            "sha256": checksum
        })

    # 4. Write JSON
    manifest_data = {"devices": devices_list}
    
    # Check if content actually changed to avoid unnecessary writes
    current_content = ""
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
            current_content = f.read()
            
    new_content = json.dumps(manifest_data, indent=2, ensure_ascii=False)
    
    if new_content != current_content:
        with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"[Success] Updated manifest.json with {len(devices_list)} models.")
    else:
        print("[Info] No changes detected in manifest structure.")

def monitor_mode(interval=2):
    """Poll directory for changes."""
    print(f"[Monitor] Watching {OTA_DIR} for changes (Ctrl+C to stop)...")
    last_mtime = 0
    
    try:
        while True:
            # Simple change detection: check modification time of the directory
            # Note: on Windows directory mtime might not update on file content change, 
            # so we iterate files to get max mtime.
            current_max_mtime = 0
            if os.path.exists(OTA_DIR):
                current_max_mtime = os.stat(OTA_DIR).st_mtime
                for f in os.listdir(OTA_DIR):
                    fp = os.path.join(OTA_DIR, f)
                    if os.path.isfile(fp):
                        current_max_mtime = max(current_max_mtime, os.stat(fp).st_mtime)
            
            if current_max_mtime > last_mtime:
                if last_mtime != 0: # Skip first loop print if desired, but good to run once
                    print("[Monitor] Change detected. Regenerating...")
                generate_manifest()
                last_mtime = current_max_mtime
            
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[Monitor] Stopped.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-generate OTA manifest.json")
    parser.add_argument("--watch", "-w", action="store_true", help="Run in monitor mode to watch for file changes")
    args = parser.parse_args()

    if args.watch:
        monitor_mode()
    else:
        generate_manifest()
