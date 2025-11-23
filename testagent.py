import requests

BASE_URL = "https://api.agi.tech/v1"
AGI_API_KEY = "49e851f1-8f2b-4565-9995-136ec665691a"

resp = requests.delete(
    f"{BASE_URL}/sessions",
    headers={"Authorization": f"Bearer {AGI_API_KEY}"},
    json={"agent_name": "agi-0"},
    timeout=60  # <-- don't hang forever
)
print(resp.status_code)
print(resp.json())
