import requests
import re
from bs4 import BeautifulSoup

# Config
BASE_URL = "http://127.0.0.1:8080/jscms" # Assuming context path is /jscms based on previous logs or war name
# Wait, war name is JSCMS.war, so path is /JSCMS
# But in docker-compose, port 8080 is exposed directly.
# Let's check container logs for context path. Standard Tomcat deploys WAR as /WAR_NAME.
# So URL is http://127.0.0.1:8080/JSCMS/

LOGIN_URL = "http://127.0.0.1:8080/JSCMS/login"
REG_URL = "http://127.0.0.1:8080/JSCMS/newDeviceInfo" # Guessing
# Or /regDeviceInfo

USERNAME = "admin"
PASSWORD = "admin"

def debug_post():
    s = requests.Session()
    
    # 1. Login
    print(f"Logging in to {LOGIN_URL}...")
    try:
        # First GET to get CSRF token if needed (Spring Security)
        r = s.get(LOGIN_URL)
        soup = BeautifulSoup(r.text, 'html.parser')
        csrf_token = soup.find('input', {'name': '_csrf'})
        data = {
            "ssoId": USERNAME, # Spring Security default param names? usually username/password
            "password": PASSWORD
        }
        if csrf_token:
            data['_csrf'] = csrf_token['value']
            print(f"Found CSRF token: {csrf_token['value']}")
            
        # Try standard Spring Security params
        r = s.post(LOGIN_URL, data=data)
        if r.url.endswith("login?error"):
            print("Login failed!")
            return
        print("Login successful.")
    except Exception as e:
        print(f"Login error: {e}")
        return

    # 2. Try to access the registration page to confirm URL and get form fields
    target_url = "http://127.0.0.1:8080/JSCMS/new"
    print(f"Accessing {target_url}...")
    r = s.get(target_url)
    
    if r.status_code != 200:
        print(f"Failed to access page: {r.status_code}")
        return

    print(f"Target URL confirmed: {target_url}")
    
    # 3. Construct Payload (Simulate Form Submit)
    # Based on regDeviceInfo.jsp analysis
    payload = {
        "id": "", # Empty for new
        "device_id": "TEST_DEV_002", # Unique ID
        "device_name": "Test Device 2",
        "mac_address": "TESTMAC00002",
        "description": "Debug script test",
        "is_active": "true",
        "last_sync_date": "2026-01-26" 
    }
    
    # Add CSRF if present in form
    soup = BeautifulSoup(r.text, 'html.parser')
    csrf_token = soup.find('input', {'name': '_csrf'})
    if csrf_token:
        payload['_csrf'] = csrf_token['value']

    print("Submitting payload...")
    r = s.post(target_url, data=payload)
    
    # 4. Analyze Response
    if r.status_code == 302:
        print("Success! Redirected to:", r.headers.get('Location'))
    else:
        print("Submission returned 200 (Likely Validation Error). Parsing errors...")
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Look for Spring form:errors (usually rendered as spans with class help-inline or similar)
        errors = soup.find_all(class_="help-inline")
        found_error = False
        for err in errors:
            if err.text.strip():
                print(f"[Validation Error] {err.parent.find_previous('label').text.strip()}: {err.text.strip()}")
                found_error = True
        
        if not found_error:
            print("No visible validation errors found. Check server logs.")
            # Print page title to be sure we are on the right page
            print("Page Title:", soup.title.string if soup.title else "No Title")

if __name__ == "__main__":
    debug_post()
