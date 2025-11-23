from flask import Flask, request, jsonify
import requests
import time
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re

app = Flask(__name__)

# --- AGI API Config ---
BASE_URL = "https://api.agi.tech/v1"
AGI_API_KEY = "49e851f1-8f2b-4565-9995-136ec665691a"

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

# --- Regular scraping functions (no AGI API) ---
def scrape_basic_info(url):
    """Scrape name, description, and contact info from main page using regular HTTP requests"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        result = {
            "name": None,
            "description": None,
            "email": None,
            "phone": None,
            "social_media": []
        }
        
        # Extract name
        name_selectors = [
            ('h1', lambda x: x.get_text(strip=True)),
            ('title', lambda x: x.get_text(strip=True)),
            ('meta[property="og:title"]', lambda x: x.get('content')),
        ]
        for selector, extractor in name_selectors:
            elem = soup.select_one(selector)
            if elem:
                name = extractor(elem)
                if name and len(name) > 2:
                    result["name"] = name
                    break
        
        # Extract description
        desc_selectors = [
            ('meta[name="description"]', lambda x: x.get('content')),
            ('meta[property="og:description"]', lambda x: x.get('content')),
        ]
        for selector, extractor in desc_selectors:
            elem = soup.select_one(selector)
            if elem:
                desc = extractor(elem)
                if desc and len(desc) > 20:
                    result["description"] = desc[:500]
                    break
        
        # Extract email from mailto links
        mailto_links = soup.select('a[href^="mailto:"]')
        if mailto_links:
            email = mailto_links[0].get('href', '').replace('mailto:', '').split('?')[0].strip()
            if email and '@' in email and '.' in email:
                result["email"] = email
        
        # Extract email from text content (regex pattern)
        if not result["email"]:
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            page_text = soup.get_text()
            emails = re.findall(email_pattern, page_text)
            if emails:
                # Filter out common false positives
                valid_emails = [e for e in emails if not any(x in e.lower() for x in ['example.com', 'test.com', 'domain.com', 'email.com'])]
                if valid_emails:
                    result["email"] = valid_emails[0]
        
        # Extract phone from tel links
        tel_links = soup.select('a[href^="tel:"]')
        if tel_links:
            phone = tel_links[0].get('href', '').replace('tel:', '').strip()
            if phone:
                result["phone"] = phone
        
        # Extract phone from text content (regex patterns)
        if not result["phone"]:
            phone_patterns = [
                r'\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # US format
                r'\+?\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}',  # International
            ]
            page_text = soup.get_text()
            for pattern in phone_patterns:
                phones = re.findall(pattern, page_text)
                if phones:
                    # Clean up the phone number
                    phone = re.sub(r'[^\d+]', '', phones[0])
                    if len(phone) >= 10:  # Valid phone should have at least 10 digits
                        result["phone"] = phone
                        break
        
        # Extract social media links from footer and all links
        social_patterns = ['facebook.com', 'instagram.com', 'twitter.com', 'x.com', 'linkedin.com', 
                          'tiktok.com', 'youtube.com', 'pinterest.com']
        social_urls = set()
        
        # Check footer first (most common location)
        footer = soup.select_one('footer')
        if footer:
            for link in footer.select('a[href]'):
                href = link.get('href', '').lower()
                for platform in social_patterns:
                    if platform in href:
                        full_url = urljoin(url, link.get('href'))
                        social_urls.add(full_url)
        
        # Also check all links for social media
        for link in soup.select('a[href]'):
            href = link.get('href', '').lower()
            for platform in social_patterns:
                if platform in href:
                    full_url = urljoin(url, link.get('href'))
                    social_urls.add(full_url)
        
        result["social_media"] = list(social_urls)
        return result
    except Exception as e:
        print(f"Scraping error: {e}")
        return {"name": None, "description": None, "email": None, "phone": None, "social_media": []}

def find_contact_page_url(base_url):
    """Find contact/support page URL by trying common Shopify paths and scraping footer"""
    base = urlparse(base_url)
    base_url_clean = f"{base.scheme}://{base.netloc}"
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # First, try to find contact links in footer
    try:
        resp = requests.get(base_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            footer = soup.select_one('footer')
            if footer:
                contact_keywords = ['contact', 'support', 'help', 'reach', 'get-in-touch', 'customer-service']
                for link in footer.select('a[href]'):
                    href = link.get('href', '').lower()
                    text = link.get_text(strip=True).lower()
                    if any(keyword in text or keyword in href for keyword in contact_keywords):
                        full_url = urljoin(base_url, link.get('href'))
                        # Verify the URL exists
                        try:
                            test_resp = requests.head(full_url, headers=headers, timeout=5, allow_redirects=True)
                            if test_resp.status_code == 200:
                                return full_url
                        except:
                            continue
    except:
        pass
    
    # Fallback to common paths
    common_paths = [
        '/pages/contact', '/contact', '/pages/support', '/support', 
        '/pages/help', '/help', '/pages/contact-us', '/contact-us'
    ]
    
    for path in common_paths:
        try:
            test_url = base_url_clean + path
            resp = requests.head(test_url, headers=headers, timeout=5, allow_redirects=True)
            if resp.status_code == 200:
                return test_url
        except:
            continue
    return None

def scrape_contact_page(url):
    """Scrape contact page for additional contact info"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        result = {"email": None, "phone": None, "social_media": []}
        
        # Extract email
        mailto_links = soup.select('a[href^="mailto:"]')
        if mailto_links:
            email = mailto_links[0].get('href', '').replace('mailto:', '').split('?')[0].strip()
            if email and '@' in email and '.' in email:
                result["email"] = email
        
        if not result["email"]:
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            page_text = soup.get_text()
            emails = re.findall(email_pattern, page_text)
            if emails:
                valid_emails = [e for e in emails if not any(x in e.lower() for x in ['example.com', 'test.com', 'domain.com', 'email.com'])]
                if valid_emails:
                    result["email"] = valid_emails[0]
        
        # Extract phone
        tel_links = soup.select('a[href^="tel:"]')
        if tel_links:
            phone = tel_links[0].get('href', '').replace('tel:', '').strip()
            if phone:
                result["phone"] = phone
        
        if not result["phone"]:
            phone_patterns = [
                r'\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
                r'\+?\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}',
            ]
            page_text = soup.get_text()
            for pattern in phone_patterns:
                phones = re.findall(pattern, page_text)
                if phones:
                    phone = re.sub(r'[^\d+]', '', phones[0])
                    if len(phone) >= 10:
                        result["phone"] = phone
                        break
        
        # Extract social media
        social_patterns = ['facebook.com', 'instagram.com', 'twitter.com', 'x.com', 'linkedin.com', 
                          'tiktok.com', 'youtube.com', 'pinterest.com']
        social_urls = set()
        for link in soup.select('a[href]'):
            href = link.get('href', '').lower()
            for platform in social_patterns:
                if platform in href:
                    full_url = urljoin(url, link.get('href'))
                    social_urls.add(full_url)
        result["social_media"] = list(social_urls)
        
        return result
    except Exception as e:
        print(f"Error scraping contact page: {e}")
        return {"email": None, "phone": None, "social_media": []}

# --- Core agent function ---
def run_vendor_agent(vendor_url):
    state_log = []
    result = {
        "name": None,
        "description": None,
        "email": None,
        "phone": None,
        "social_media": [],
        "state_log": state_log
    }

    # --- Step 1: Try regular scraping first (FREE, no AGI API credits) ---
    print("Step 1: Scraping main page with regular HTTP requests...")
    scraped_data = scrape_basic_info(vendor_url)
    state_log.append({"step": "Regular Scraping", "success": True})
    
    # Use scraped data as baseline
    result["name"] = scraped_data.get("name")
    result["description"] = scraped_data.get("description")
    result["email"] = scraped_data.get("email")
    result["phone"] = scraped_data.get("phone")
    result["social_media"] = scraped_data.get("social_media", [])
    
    print(f"Scraped main page: name={result['name']}, email={result['email']}, phone={result['phone']}, social={len(result['social_media'])}")
    
    # --- Step 1.5: Also scrape contact page if found (FREE) ---
    contact_url = find_contact_page_url(vendor_url)
    if contact_url and contact_url != vendor_url:
        print(f"Step 1.5: Found contact page, scraping it: {contact_url}")
        contact_data = scrape_contact_page(contact_url)
        # Merge contact page data (fill missing fields)
        if not result["email"] and contact_data.get("email"):
            result["email"] = contact_data.get("email")
        if not result["phone"] and contact_data.get("phone"):
            result["phone"] = contact_data.get("phone")
        # Merge social media
        existing_social = set(result["social_media"])
        for url in contact_data.get("social_media", []):
            if url not in existing_social:
                result["social_media"].append(url)
        print(f"After contact page scrape: email={result['email']}, phone={result['phone']}, social={len(result['social_media'])}")
    
    # Check if we need AGI API (prioritize email/phone over social media)
    # Only skip AGI if we have email OR phone (social media alone is not enough)
    has_email_or_phone = result["email"] or result["phone"]
    
    if has_email_or_phone:
        print(f"✓ Email/phone found via scraping (email={result['email']}, phone={result['phone']}). Skipping AGI API (saving credits).")
        return result
    
    # If we only have social media but no email/phone, still use AGI to find email/phone
    if result["social_media"]:
        print(f"Found {len(result['social_media'])} social media links, but email/phone missing. Using AGI API to find email/phone...")
    else:
        print("No email, phone, or social media found. Using AGI API to find contact info...")
    
    # --- Step 2: Use AGI API ONLY for finding contact info on support/help pages ---
    print("Step 2: Contact info still missing. Using AGI API to navigate to support/help pages...")
    
    if not contact_url:
        print("No contact page found via common paths, will use AGI to find it")
        contact_url = vendor_url

    # --- Step 3: Create AGI session (only when needed) ---
    def create_session():
        print("Creating AGI session...")
        resp = requests.post(
            f"{BASE_URL}/sessions",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            json={"agent_name": "agi-0"},
            timeout=60
        )
        resp.raise_for_status()
        return resp.json().get("session_id")

    session_id, state = retry_request(create_session)
    state_log.append({"step": "Create AGI Session", **state})
    if not state["success"]:
        return result

    # --- Step 4: Send minimal, targeted instructions (only for contact info) ---
    def send_task():
        message = f"""
            You are on: {contact_url}
            
            YOUR TASK: Find contact information (email, phone, or social media links).
            
            STEP 1: Look on the current page for:
            - Email addresses (check mailto: links, text content, contact forms)
            - Phone numbers (check tel: links, text content)
            - Social media links (Facebook, Instagram, Twitter/X, LinkedIn, TikTok, YouTube, Pinterest)
            
            STEP 2: If you don't find contact info, navigate to other pages:
            1. Scroll to the bottom of the page to see the footer
            2. Look for links with text like: "Support", "Help", "Contact", "Contact Us", "Get in Touch", "Customer Service"
            3. Click on those links to go to contact/support pages
            4. Extract contact info from those pages
            
            STEP 3: Return your findings as JSON:
            {{
                "email": "email@example.com" or null,
                "phone": "+1-234-567-8900" or null,
                "social_media": ["https://facebook.com/page", "https://instagram.com/page"] or []
            }}
            
            IMPORTANT: You must find at least ONE contact method (email, phone, or social media). Keep searching until you find something.
        """
        print("Sending targeted AGI instructions for contact info...")
        resp = requests.post(
            f"{BASE_URL}/sessions/{session_id}/message",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            json={"message": message},
            timeout=60
        )
        resp.raise_for_status()
        return True

    _, state = retry_request(send_task)
    state_log.append({"step": "Send AGI Instructions", **state})
    if not state["success"]:
        # Cleanup on failure
        try:
            requests.delete(f"{BASE_URL}/sessions/{session_id}", headers={"Authorization": f"Bearer {AGI_API_KEY}"}, timeout=10)
        except:
            pass
        return result

    # --- Step 5: Monitor progress (reduced wait time since we're only getting contact info) ---
    finished = False
    attempt = 0
    while not finished and attempt < 30:  # Increased to allow more time for navigation
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
        if status:
            status_value = status.get("status", "unknown")
            print(f"AGI status check {attempt}: {status_value}")
            if status_value in ["finished", "error"]:
                finished = True
            else:
                time.sleep(3)  # Increased wait time for navigation
        else:
            time.sleep(3)

    # --- Step 6: Get results ---
    def get_results():
        resp = requests.get(
            f"{BASE_URL}/sessions/{session_id}/messages",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            timeout=30
        )
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
        print(f"Received {len(messages)} messages from AGI")
        
        for msg in messages:
            msg_type = msg.get("type", "")
            content = msg.get("content", "")
            print(f"Message type: {msg_type}, content preview: {str(content)[:200] if content else 'empty'}")
            
            if msg_type == "DONE":
                try:
                    if isinstance(content, str):
                        content = json.loads(content)
                    print(f"Parsed AGI response: {content}")
                    return content
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"Failed to parse AGI response as JSON: {e}")
                    # Try to extract email/phone from plain text
                    if isinstance(content, str):
                        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', content)
                        phone_match = re.search(r'\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', content)
                        result = {}
                        if email_match:
                            result["email"] = email_match.group(0)
                        if phone_match:
                            result["phone"] = phone_match.group(0)
                        if result:
                            return result
                    return {}
        return {}

    agi_data, state = retry_request(get_results)
    state_log.append({"step": "Get AGI Results", **state})
    
    # Merge AGI results (only fill missing contact fields)
    if agi_data:
        if not result["email"] and agi_data.get("email"):
            result["email"] = agi_data.get("email")
        if not result["phone"] and agi_data.get("phone"):
            result["phone"] = agi_data.get("phone")
        agi_social = agi_data.get("social_media", [])
        if isinstance(agi_social, list):
            # Merge social media, avoiding duplicates
            existing_social = set(result["social_media"])
            for url in agi_social:
                if url not in existing_social:
                    result["social_media"].append(url)
        
        print(f"AGI found: email={result['email']}, phone={result['phone']}, social={len(result['social_media'])}")

    # --- Step 7: Cleanup ---
    try:
        requests.delete(f"{BASE_URL}/sessions/{session_id}", headers={"Authorization": f"Bearer {AGI_API_KEY}"}, timeout=10)
    except:
        pass
    state_log.append({"step": "Cleanup", "success": True})

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
