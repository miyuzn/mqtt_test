import requests
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WEB_URL = "https://127.0.0.1:5000"
BACKEND_URL = "http://127.0.0.1:5001"
USERNAME = "admin"
PASSWORD = "admin"

def measure_stream(url, cookies=None, label="Stream"):
    print(f"\n--- Testing {label}: {url} ---")
    try:
        start_conn = time.time()
        with requests.get(url, cookies=cookies, stream=True, verify=False, timeout=5) as r:
            print(f"Connected in {time.time() - start_conn:.3f}s. Status: {r.status_code}")
            if r.status_code != 200:
                print("Failed to connect.")
                return

            count = 0
            start_read = time.time()
            total_bytes = 0
            
            # Read 50 chunks or run for 5 seconds
            for chunk in r.iter_content(chunk_size=4096):
                if not chunk: continue
                total_bytes += len(chunk)
                count += 1
                if count % 10 == 0:
                    print(f"Received {count} chunks...")
                if count >= 50 or (time.time() - start_read) > 5:
                    break
            
            duration = time.time() - start_read
            print(f"Result: {count} chunks, {total_bytes/1024:.2f} KB in {duration:.3f}s")
            print(f"Rate: {count/duration:.1f} chunks/s, {total_bytes/1024/duration:.1f} KB/s")

    except Exception as e:
        print(f"Error: {e}")

def main():
    # 1. Login to Web
    s = requests.Session()
    print("Logging in...")
    try:
        r = s.post(f"{WEB_URL}/login", data={"username": USERNAME, "password": PASSWORD}, verify=False)
        if r.status_code != 200:
            print(f"Login failed: {r.status_code}")
            # return # 即使登录失败，也可以测试 Backend
        else:
            print("Login successful.")
    except Exception as e:
        print(f"Login error: {e}")
        
    cookies = s.cookies.get_dict()

    # 2. Test Web Stream (Proxy)
    measure_stream(f"{WEB_URL}/stream", cookies=cookies, label="Web Proxy")

    # 3. Test Backend Stream (Direct)
    # Backend usually doesn't need auth or uses basic auth if configured? 
    # Based on docker-compose, backend internal auth is empty vars USERNAME=/PASSWORD=.
    # But let's try direct access.
    measure_stream(f"{BACKEND_URL}/stream", label="Direct Backend")

if __name__ == "__main__":
    main()
