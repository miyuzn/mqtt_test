import psycopg2
import sys

# Config from jscms container analysis
DB_NAME = "jscms"
DB_USER = "postgres"
DB_PASS = "123456"
DB_HOST = "163.143.136.103"
DB_PORT = "5432"

def get_groups():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT,
            connect_timeout=5
        )
        cur = conn.cursor()
        cur.execute("SELECT group_id FROM user_group LIMIT 5")
        rows = cur.fetchall()
        print("\n--- Available Groups ---")
        for row in rows:
            print(f"- {row[0]}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    get_groups()

