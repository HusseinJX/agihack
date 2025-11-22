# vendor_agent_flask.py
import requests
from bs4 import BeautifulSoup
import time
import json
from flask import Flask, request, jsonify
from flask_cors import CORS

MAX_RETRIES = 3
WAIT_BETWEEN_RETRIES = 1  # seconds

app = Flask(__name__)
CORS(app)

# Initialize state
state = {
    "logs": [],
    "retries": {},
    "fallbacks_used": []
}

# ---------- Helper Functions ----------
def retry_action(step_name, action_fn, verify_fn, fallback):
    """Generic retry/verify/fallback wrapper"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = action_fn()
            if verify_fn(result):
                state["logs"].append(f"{step_name} succeeded on attempt {attempt}")
                state["retries"][step_name] = attempt - 1
                return result
            else:
                state["logs"].append(f"{step_name} verification failed on attempt {attempt}")
        except Exception as e:
            state["logs"].append(f"{step_name} error on attempt {attempt}: {e}")
        time.sleep(WAIT_BETWEEN_RETRIES)

    state["logs"].append(f"{step_name} failed, using fallback")
    state["fallbacks_used"].append(step_name)
    return fallback

def dom_first(soup, selectors, default=""):
    """Try a list of selectors, return first non-empty"""
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return default

# ---------- 10-Step Agent Workflow ----------
def run_vendor_onboarding(vendor_url):
    vendor_data = {
        "name": "",
        "logo": "",
        "description": "",
        "contact": {"emails": [], "phones": []},
        "location": "",
        "social_links": []
    }
    products_data = []

    # Step 0: Open page
    def step0():
        r = requests.get(vendor_url, timeout=5)
        return BeautifulSoup(r.text, "lxml")
    soup = retry_action("Open Vendor Page", step0, lambda x: x is not None, None)
    if soup is None:
        return {"vendor": vendor_data, "products": products_data, "state": state}

    # Step 1: Extract Vendor Name
    def step1():
        return dom_first(soup, ["title", "h1", "meta[name='title']"], default=vendor_url)
    vendor_data["name"] = retry_action("Extract Vendor Name", step1, lambda x: len(x) > 0, vendor_url)

    # Step 2: Extract Logo
    def step2():
        return dom_first(soup, ["img[alt*='logo']", "img[class*='logo']"], default="")
    vendor_data["logo"] = retry_action("Extract Vendor Logo", step2, lambda x: x != "", "")

    # Step 3: Extract Description
    def step3():
        return dom_first(soup, ["meta[name='description']", "p"], default="")
    vendor_data["description"] = retry_action("Extract Description", step3, lambda x: len(x) > 0, "")

    # Step 4: Extract Contact Info (simplified)
    def step4():
        emails = [a.get('href').replace("mailto:", "") for a in soup.select("a[href^=mailto]")]
        phones = []  # Add regex scanning if needed
        return {"emails": emails, "phones": phones}
    vendor_data["contact"] = retry_action("Extract Contact Info", step4, lambda x: True, {"emails": [], "phones": []})

    # Step 5: Extract Location
    def step5():
        return dom_first(soup, ["address", "footer"], default="Unknown")
    vendor_data["location"] = retry_action("Extract Location", step5, lambda x: len(x) > 0, "Unknown")

    # Step 6: Extract Social Links
    def step6():
        links = [a['href'] for a in soup.select("a[href*='facebook'], a[href*='instagram'], a[href*='twitter']")]
        return links
    vendor_data["social_links"] = retry_action("Extract Social Links", step6, lambda x: isinstance(x, list), [])

    # Step 7: Extract Products (simplified, placeholder)
    def step7():
        product_divs = soup.select("div[class*='product'], li[class*='item']")
        products = []
        for div in product_divs:
            name = div.select_one("h2,h3,h4")
            name_text = name.get_text(strip=True) if name else "Unnamed Product"
            products.append({"name": name_text, "image": "", "price": "", "description": "", "category": ""})
        return products
    products_data = retry_action("Extract Products", step7, lambda x: isinstance(x, list), [])

    # Step 8: Infer Categories
    def step8():
        for p in products_data:
            if not p.get("category"):
                p["category"] = "Uncategorized"
        return products_data
    products_data = retry_action("Infer Categories", step8, lambda x: True, products_data)

    # Step 9: Assemble JSON
    def step9():
        return {"vendor": vendor_data, "products": products_data, "state": state}
    final_output = retry_action("Assemble JSON", step9, lambda x: True, {"vendor": vendor_data, "products": products_data, "state": state})

    return final_output

# ---------- Flask Endpoint ----------
@app.route("/run-agent", methods=["POST"])
def run_agent_endpoint():
    vendor_url = request.json.get("url")
    if not vendor_url:
        return jsonify({"error": "No URL provided"}), 400
    result = run_vendor_onboarding(vendor_url)
    return jsonify(result)

# ---------- Run Flask ----------
if __name__ == "__main__":
    app.run(port=5000, debug=True)
