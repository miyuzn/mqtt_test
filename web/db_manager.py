import os
import psycopg2
from psycopg2 import pool, extras

# 从环境变量加载配置
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

# 全局连接池
_pg_pool = None

def init_db_pool():
    global _pg_pool
    if _pg_pool is None:
        try:
            _pg_pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASS
            )
            print(f"[DB] Connection pool initialized for {DB_HOST}")
        except Exception as e:
            print(f"[DB] Failed to initialize pool: {e}")

def get_db_connection():
    if _pg_pool is None:
        init_db_pool()
    return _pg_pool.getconn()

def release_db_connection(conn):
    if _pg_pool and conn:
        _pg_pool.putconn(conn)

def authenticate_user(username, password):
    """
    验证用户登录。
    Returns: user_dict {'id': int, 'sso_id': str} or None
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            # TODO: 未来应升级为 bcrypt 校验
            cur.execute("SELECT id, sso_id, password FROM app_user WHERE sso_id = %s", (username,))
            user = cur.fetchone()
            
            if user:
                # 明文比对
                if user['password'] == password:
                    return {'id': user['id'], 'sso_id': user['sso_id']}
    except Exception as e:
        print(f"[DB] Auth error: {e}")
    finally:
        release_db_connection(conn)
    return None

def get_user_allowed_devices(username):
    """
    获取用户有权访问的设备列表。
    Admin 账号拥有所有权限。
    Returns: List of dicts [{'device_id': str, 'mac_address': str}, ...]
    """
    conn = None
    devices = []
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            if username == 'admin':
                # 超级管理员：获取所有设备
                cur.execute("SELECT device_id, mac_address FROM device_info")
            else:
                # 普通用户：根据组关联查询
                sql = """
                    SELECT d.device_id, d.mac_address 
                    FROM device_info d
                    JOIN user_group ug ON d.group_id = ug.group_id
                    JOIN app_user_user_group map ON ug.id = map.user_group_id
                    JOIN app_user u ON map.user_id = u.id
                    WHERE u.sso_id = %s
                """
                cur.execute(sql, (username,))
            
            rows = cur.fetchall()
            for row in rows:
                devices.append({
                    'device_id': row['device_id'],
                    'mac_address': row['mac_address']
                })
    except Exception as e:
        print(f"[DB] Permission query error: {e}")
    finally:
        release_db_connection(conn)
    return devices

def get_user_files(username):
    """
    获取用户有权下载的文件列表。
    """
    conn = None
    files = []
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            if username == 'admin':
                cur.execute("""
                    SELECT f.file_name, f.file_path, f.mac_address, f.file_size, f.file_date 
                    FROM data_files f 
                    ORDER BY f.file_datetime DESC LIMIT 100
                """)
            else:
                # 仅查询用户所属组下的设备产生的文件
                sql = """
                    SELECT f.file_name, f.file_path, f.mac_address, f.file_size, f.file_date
                    FROM data_files f
                    JOIN device_info d ON f.mac_address = d.mac_address
                    JOIN user_group ug ON d.group_id = ug.group_id
                    JOIN app_user_user_group map ON ug.id = map.user_group_id
                    JOIN app_user u ON map.user_id = u.id
                    WHERE u.sso_id = %s
                    ORDER BY f.file_datetime DESC LIMIT 100
                """
                cur.execute(sql, (username,))
            
            rows = cur.fetchall()
            for row in rows:
                files.append(dict(row))
    except Exception as e:
        print(f"[DB] File query error: {e}")
    finally:
        release_db_connection(conn)
    return files

def get_device_dates(mac):
    """
    Get distinct dates for a device.
    """
    conn = None
    dates = []
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT file_date 
                FROM data_files 
                WHERE mac_address = %s
                ORDER BY file_date DESC
            """, (mac,))
            rows = cur.fetchall()
            dates = [row[0] for row in rows]
    except Exception as e:
        print(f"[DB] Date query error: {e}")
    finally:
        release_db_connection(conn)
    return dates

def get_device_files(mac, date_str):
    """
    Get files for a specific device and date.
    """
    conn = None
    files = []
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=extras.DictCursor) as cur:
            cur.execute("""
                SELECT file_name, file_path, file_size, file_time 
                FROM data_files 
                WHERE mac_address = %s AND file_date = %s
                ORDER BY file_time DESC
            """, (mac, date_str))
            rows = cur.fetchall()
            for row in rows:
                files.append(dict(row))
    except Exception as e:
        print(f"[DB] File list query error: {e}")
    finally:
        release_db_connection(conn)
    return files
