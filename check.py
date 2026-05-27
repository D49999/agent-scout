# check.py
import os, requests
token = os.environ.get("GITHUB_TOKEN")
print("Token 前6位:", (token or "")[:6], "长度:", len(token or ""))
r = requests.get(
    "https://api.github.com/rate_limit",
    headers={"Authorization": f"Bearer {token}"} if token else {},
    timeout=15,
)
print("HTTP状态:", r.status_code)
print("限流上限:", r.json().get("rate", {}).get("limit"))
