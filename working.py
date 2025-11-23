from flask import Flask, request, jsonify
import requests
import time

app = Flask(__name__)

# --- AGI API Config ---
BASE_URL = "https://api.agi.tech/v1"
AGI_API_KEY = "YOUR_API_KEY_HERE"

# --- Retry utility ---
def retry_request(func, retries=3, delay=5):
    for attempt in range(1, retries + 1):
        try:
            result = func()
            return result, {"success": True, "attempts": attempt}
        except Exception as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt == retries:
                return None, {"success": False, "error": str(e), "attempts": attempt}
            time.sleep(delay)

# --- Core agent function ---
def run_vendor_agent(vendor_url):
    state_log = []
    result = {"vendor": {}, "products": [], "state_log": state_log}

    # --- Step 1: Create session ---
    def create_session():
        print("Creating AGI session...")
        resp = requests.post(
            f"{BASE_URL}/sessions",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            json={"agent_name": "agi-0"},
            timeout=60
        )
        resp.raise_for_status()
        return resp.json()["session_id"]

    session_id, state = retry_request(create_session)
    state_log.append({"step": "Create Session", **state})
    if not state["success"]:
        return result

    # --- Step 2: Send instructions ---
    def send_task():
        message = f"""
            Go to the Shopify vendor page: {vendor_url}
            Extract structured data:
            - Vendor name
            - Logo URL
            - Description
            - Contact info (emails/phones)
            - Location
            Return as JSON.
        """
        print("Sending instructions to AGI agent...")
        resp = requests.post(
            f"{BASE_URL}/sessions/{session_id}/message",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            json={"message": message},
            timeout=60
        )
        resp.raise_for_status()
        return True

    _, state = retry_request(send_task)
    state_log.append({"step": "Send Instructions", **state})
    if not state["success"]:
        return result

    # --- Step 3: Monitor progress ---
    finished = False
    attempt = 0
    while not finished and attempt < 30:
        attempt += 1
        def get_status():
            resp = requests.get(
                f"{BASE_URL}/sessions/{session_id}/status",
                headers={"Authorization": f"Bearer {AGI_API_KEY}"},
                timeout=30
            )
            resp.raise_for_status()
            return resp.json()

        status, _ = retry_request(get_status)
        print(f"Checking agent status... attempt {attempt}")
        if status and status.get("status") in ["finished", "error"]:
            finished = True
        else:
            time.sleep(2)

    # --- Step 4: Get results ---
    def get_results():
        resp = requests.get(
            f"{BASE_URL}/sessions/{session_id}/messages",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            timeout=30
        )
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
        for msg in messages:
            if msg.get("type") == "DONE":
                return msg.get("content")
        return {}

    data, state = retry_request(get_results)
    state_log.append({"step": "Get Results", **state})
    if data:
        result["vendor"] = data.get("vendor", {})
        result["products"] = data.get("products", [])

    # --- Step 5: Cleanup session ---
    def cleanup():
        resp = requests.delete(
            f"{BASE_URL}/sessions/{session_id}",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            timeout=30
        )
        resp.raise_for_status()
        return True

    _, state = retry_request(cleanup)
    state_log.append({"step": "Cleanup Session", **state})

    return result

# --- Flask route ---
@app.route("/run-agent", methods=["POST"])
def run_agent():
    data = request.get_json()
    vendor_url = data.get("vendor_url")
    if not vendor_url:
        return jsonify({"error": "Missing vendor_url"}), 400

    result = run_vendor_agent(vendor_url)
    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)
