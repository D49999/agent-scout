import requests
try:
    r = requests.get("https://api.github.com", timeout=15)
    print("OK", r.status_code, r.text[:200])
except Exception as e:
    print("ERR", type(e).__name__, e)