import psycopg2
import sys

# Config from jscms container analysis
DB_NAME = "jscms"
DB_USER = "postgres"
DB_PASS = "123456"
DB_HOST = "163.143.136.103"
DB_PORT = "5432"

def check_constraint():
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
        cur.execute("""
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint 
            WHERE conrelid = 'data_files'::regclass
        """)
        rows = cur.fetchall()
        print("\n--- Constraints on data_files ---")
        for row in rows:
            print(f"Name: {row[0]}")
            print(f"Def:  {row[1]}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    check_constraint()

