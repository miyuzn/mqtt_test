import os
import pathlib
import psycopg2
from datetime import datetime

# Config
STORE_DIR = "backend/mqtt_store"
DB_HOST = "163.143.136.103"
DB_PORT = "5432"
DB_NAME = "jscms"
DB_USER = "postgres"
DB_PASS = "123456"
TARGET_GROUP = "A"

def main():
    root = pathlib.Path(STORE_DIR)
    if not root.exists():
        print(f"Store directory not found: {STORE_DIR}")
        return

    # 1. Scan Disk for MACs
    disk_macs = set()
    for d in root.iterdir():
        if d.is_dir() and len(d.name) >= 4: # Simple filter
            disk_macs.add(d.name)
    
    print(f"Found {len(disk_macs)} potential devices on disk.")

    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        cur = conn.cursor()

        # 2. Get Existing MACs
        cur.execute("SELECT mac_address FROM device_info")
        existing_macs = {row[0] for row in cur.fetchall()}
        
        # 3. Identify Missing
        missing_macs = disk_macs - existing_macs
        if not missing_macs:
            print("All devices are already registered.")
            return

        print(f"Registering {len(missing_macs)} new devices...")
        
        # 4. Insert Missing
        count = 0
        for i, mac in enumerate(missing_macs):
            # Generate unique ID to avoid collision with existing data
            # Use full MAC to ensure uniqueness
            # device_id limited to 15 chars. A_ + 12 chars = 14 chars.
            device_id = f"A_{mac}"
            device_name = f"Auto Discovered {mac}"
            
            try:
                cur.execute("""
                    INSERT INTO device_info 
                    (device_id, device_name, mac_address, description, is_active, group_id, last_sync_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    device_id, 
                    device_name, 
                    mac, 
                    "Auto-registered by script", 
                    True, 
                    TARGET_GROUP, 
                    datetime.now().date()
                ))
                count += 1
            except Exception as e:
                print(f"Failed to insert {mac}: {e}")
                conn.rollback() # Rollback transaction for this failure
                continue
            
            conn.commit() # Commit each success
            
        print(f"Successfully registered {count} devices.")

    except Exception as e:
        print(f"Database error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    main()
