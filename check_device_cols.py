import psycopg2
import sys

# Config from jscms container analysis
DB_NAME = "jscms"
DB_USER = "postgres"
DB_PASS = "123456"
DB_HOST = "163.143.136.103"
DB_PORT = "5432"

def describe_device_info():
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
        cur.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'device_info'
        """)
        cols = cur.fetchall()
        print("\n--- Columns in device_info ---")
        for col in cols:
            print(f"  {col[0]}: {col[1]}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    describe_device_info()

