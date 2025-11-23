"""
Simple Flask + AGI-orchestrator example: Fly-Out Assistant

This is a single-file Python app that demonstrates how to orchestrate a "fly someone out" workflow.
It provides a minimal web UI for input and then runs a linear workflow:
 1. Buy flight at https://real-flyunified.vercel.app/
 2. Order Uber at https://real-udriver.vercel.app/ timed shortly after landing
 3. Book dining (OpenDining) OR order food (DoorDash clone) at provided URLs
 4. Book lodging (Airbnb or Marriott clone)
 5. Add events to a calendar at https://real-gocalendar.vercel.app/calendar

Important notes:
 - The remote services used here are placeholders. Adjust request bodies / auth to match each service's API.
 - This app DOES NOT perform real payments. Treat the HTTP calls as examples.
 - Configure environment variables for secrets (AGI API key, any provider credentials) before running.

How to run:
 1. python3 -m venv venv
 2. source venv/bin/activate
 3. pip install flask requests python-dotenv
 4. export AGI_API_KEY="your_agi_api_key"  # or use a .env file
 5. python flyout_app.py
 6. Open http://127.0.0.1:5000

"""

from flask import Flask, request, render_template_string, jsonify
import os
import requests
import datetime
import time
import json
from urllib.parse import urljoin

app = Flask(__name__)

# Configuration (use environment variables in production)
AGI_API_KEY = os.getenv("AGI_API_KEY", "49e851f1-8f2b-4565-9995-136ec665691a")
AGI_BASE_URL = os.getenv("AGI_BASE_URL", "https://api.agi.tech/v1")


# Remote service endpoints (provided by the user). These are used as example POST targets.
ENDPOINTS = {
    "flight": "https://real-flyunified.vercel.app/api/book",        # example
    "uber": "https://real-udriver.vercel.app/api/order",
    "opendining": "https://real-opendining.vercel.app/api/book",
    "doordash": "https://real-dashdish.vercel.app/api/order",
    "airbnb": "https://real-staynb.vercel.app/api/book",
    "marriott": "https://real-marrisuite.vercel.app/api/book",
    "calendar": "https://real-gocalendar.vercel.app/calendar/api/events",
}



@app.route('/')
def index():
    return render_template_string(open('u2i.html').read())


@app.route('/start', methods=['POST'])
def start_workflow():
    print("\n=== Starting Fly-Out Workflow ===")
    data = request.form.to_dict()
    print(f"Received data: {data}")
    
    # parse and validate inputs
    try:
        # depart_date = datetime.datetime.strptime(data.get('depart_date'), '%b %d, %Y').date()
        depart_date = datetime.datetime(2024, 7, 19)

    except Exception as e:
        error_msg = f"Invalid depart_date. Use YYYY-MM-DD. ({e})"
        print(f"ERROR: {error_msg}")
        return error_msg, 400

    return_date = None
    if data.get('return_date'):
        try:
            return_date = datetime.datetime.strptime(data.get('return_date'), '%Y-%m-%d').date()
        except Exception as e:
            error_msg = f"Invalid return_date. Use YYYY-MM-DD. ({e})"
            print(f"ERROR: {error_msg}")
            return error_msg, 400

    workflow_payload = {
        'from': data.get('from_location'),
        'to': 'SFO',
        'depart_date': str(depart_date),
        'eat_mode': data.get('eat_mode'),
        'lodging': data.get('lodging'),
        'num_travelers': int(data.get('num_travelers', 1)),
    }
    
    print(f"Workflow payload: {workflow_payload}")
    # return jsonify(workflow_payload)

    # Run the orchestration synchronously and return results as JSON.
    # NOTE: for production, make these tasks asynchronous and add retries, idempotency keys, and secure payment handling.
    try:
        result = run_flyout_workflow(workflow_payload)
        print(f"Workflow completed. Result: {result}")
        return jsonify(result)
    except Exception as e:
        error_msg = f"Workflow failed with exception: {str(e)}"
        print(f"EXCEPTION: {error_msg}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': error_msg, 'traceback': traceback.format_exc()}), 500

# ------------------------
# AGI Helper Functions
# ------------------------

def retry_request(func, retries=3, delay=5):
    """Retry a function call with exponential backoff"""
    for attempt in range(1, retries + 1):
        try:
            result = func()
            return result, {"success": True, "attempts": attempt}
        except Exception as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt == retries:
                return None, {"success": False, "error": str(e), "attempts": attempt}
            time.sleep(delay)
    return None, {"success": False, "error": "Max retries exceeded"}

def create_agi_session():
    """Create a new AGI session"""
    def _create():
        print("Creating AGI session...")
        resp = requests.post(
            f"{AGI_BASE_URL}/sessions",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            json={"agent_name": "agi-0"},
            timeout=60
        )
        resp.raise_for_status()
        return resp.json()["session_id"]
    
    session_id, state = retry_request(_create)
    return session_id, state

def send_agi_message(session_id, message):
    """Send a message to an AGI agent"""
    def _send():
        resp = requests.post(
            f"{AGI_BASE_URL}/sessions/{session_id}/message",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            json={"message": message},
            timeout=60
        )
        resp.raise_for_status()
        return True
    
    result, state = retry_request(_send)
    return result, state

def wait_for_agi_completion(session_id, max_attempts=300, delay=5):
    """Wait for AGI agent to complete task"""
    finished = False
    attempt = 0
    while not finished and attempt < max_attempts:
        attempt += 1
        def _get_status():
            resp = requests.get(
                f"{AGI_BASE_URL}/sessions/{session_id}/status",
                headers={"Authorization": f"Bearer {AGI_API_KEY}"},
                timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        
        status, _ = retry_request(_get_status)
        if status and status.get("status") in ["finished", "error"]:
            finished = True
        else:
            time.sleep(delay)
    
    return status

def get_agi_results(session_id):
    """Get results from AGI agent"""
    def _get_results():
        resp = requests.get(
            f"{AGI_BASE_URL}/sessions/{session_id}/messages",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            timeout=30
        )
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
        for msg in messages:
            if msg.get("type") == "DONE":
                return msg.get("content")
        return {}
    
    data, state = retry_request(_get_results)
    return data, state

def cleanup_agi_session(session_id):
    """Clean up AGI session"""
    def _cleanup():
        resp = requests.delete(
            f"{AGI_BASE_URL}/sessions/{session_id}",
            headers={"Authorization": f"Bearer {AGI_API_KEY}"},
            timeout=30
        )
        resp.raise_for_status()
        return True
    
    _, state = retry_request(_cleanup)
    return state

# ------------------------
# Workflow helper functions
# ------------------------

def run_flyout_workflow(p):
    """Main linear workflow using AGI agents. Each step uses an AGI agent to perform the task."""
    timeline = []
    state_log = []

    # 1) Buy flight using AGI
    print("\n[Step 1/5] Using AGI agent to book flight...")
    flight_resp = buy_flight_agi(p, state_log)
    print(f"Flight result: {flight_resp}")
    timeline.append({'step': 'buy_flight', 'result': flight_resp})



    # 2) Order Uber using AGI (needs flight details for timing)
    print("\n[Step 2/5] Using AGI agent to order Uber...")
    # if flight_resp.get('success'):
    #     uber_resp = order_uber_agi(p, flight_resp, state_log)
    # else:
    #     print("Skipping Uber order due to flight failure")
    #     uber_resp = {'success': False, 'error': 'Skipped due to flight failure'}
    # print(f"Uber result: {uber_resp}")
    # timeline.append({'step': 'order_uber', 'result': uber_resp})

    uber_resp = order_uber_agi(p, state_log)
    print(f"Uber result: {uber_resp}")
    timeline.append({'step': 'order_uber', 'result': uber_resp})



    # 3) Book lodging using AGI
    print("\n[Step 3/5] Using AGI agent to book lodging...")
    lodging_resp = book_lodging_agi(p, state_log)
    print(f"Lodging result: {lodging_resp}")
    timeline.append({'step': 'book_lodging', 'result': lodging_resp})


    # 4) Book dining using AGI
    print("\n[Step 4/5] Using AGI agent to book dining...")
    dining_resp = book_dining_agi(p, state_log)
    print(f"Dining result: {dining_resp}")
    timeline.append({'step': 'book_dining', 'result': dining_resp})


    # 5) Book calendar using AGI
    print("\n[Step 5/5] Using AGI agent to book calendar...")
    calendar_resp = book_calendar_agi(p, state_log)
    print(f"Calendar result: {calendar_resp}")
    timeline.append({'step': 'book_calendar', 'result': calendar_resp})

    return {
        'success': True,
        'timeline': timeline,
        'state_log': state_log,
    }



def buy_flight_agi(p, state_log):
    """Book a flight using the AGI agent. Returns a dict with booking results."""
    session_id = None
    try:
        # 1. Create AGI session
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Flight)", **state})
        if not state.get("success"):
            return {'success': False, 'error': 'Failed to create AGI session'}

        # 2. Compose concise booking instructions
        message = (
            f"Go to {ENDPOINTS['flight']} and book a flight with:\n"
            f"- From: {p['from']}\n"
            f"- To: {p['to']}\n"
            f"- Departure date: {p['depart_date']}\n"
            f"- Number of passengers: {p['num_travelers']}\n\n"
            f"- Passenger details: firstname: Belle, lastname: Vue, gender: F, dateofbirth: August 12 2000\n"
            "Return JSON only, with keys: success, confirmation_number, "
            "departure_time, arrival_time, flight_number, price, status, details. "
            "If failed, set success:false and include error."
        )

        # 3. Send booking request to AGI
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Flight Booking Task", **state})
        if not state.get("success"):
            return {'success': False, 'error': 'Failed to send task to AGI agent'}

        # 4. Wait for completion & collect result
        print("  Waiting for AGI agent to complete flight booking...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Flight Booking", "status": status})
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Flight Booking Results", **state})

        # 5. Parse and return result
        if not data:
            return {'success': False, 'error': 'No results from AGI agent'}
        try:
            if isinstance(data, str):
                data = json.loads(data)
        except Exception as e:
            print(f"  Error parsing AGI response: {e}")
            return {'success': False, 'error': f'Failed to parse response: {e}'}
        if data.get('success'):
            return {
                'success': True,
                'details': data,
                'arrival_time': data.get('arrival_time'),
                'confirmation_number': data.get('confirmation_number')
            }
        return {'success': False, 'error': data.get('error', 'Booking failed')}
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Flight)", **cleanup_state})


# step 2: order uber using AGI
def order_uber_agi(p, state_log):
    """Order a Uber using the AGI agent. 
    
    Args:
        p: Workflow payload with location and traveler info
        state_log: State log for tracking workflow steps
    
    Returns:
        dict with success status and ordering details
    """
    session_id = None
    
    # Calculate pickup time (15 minutes after flight arrival)
    # if arrival_time:
    #     try:
    #         # Parse arrival time (could be ISO string or datetime)
    #         if isinstance(arrival_time, str):
    #             arrival_dt = datetime.datetime.fromisoformat(arrival_time.replace('Z', '+00:00'))
    #         else:
    #             arrival_dt = arrival_time
    #         pickup_time = arrival_dt + datetime.timedelta(minutes=15)
    #         pickup_time_str = pickup_time.isoformat()
    #     except Exception as e:
    #         print(f"  Warning: Could not parse arrival_time '{arrival_time}': {e}")
    #         # Fallback: use depart_date + 3 hours + 15 minutes
    #         depart_dt = datetime.datetime.fromisoformat(p['depart_date'])
    #         pickup_time = depart_dt + datetime.timedelta(hours=3, minutes=15)
    #         pickup_time_str = pickup_time.isoformat()
    # else:
        # # Fallback if no arrival time
        # depart_dt = datetime.datetime.fromisoformat(p['depart_date'])
        # pickup_time = depart_dt + datetime.timedelta(hours=3, minutes=15)
        # pickup_time_str = pickup_time.isoformat()
        # print(f"  Warning: No arrival_time in flight response, using fallback: {pickup_time_str}")
    
    
    data = {
        "pickup_location": "100 Van Ness",
        "dropoff_location": "1 Hotel San Francisco",
        "pickup_time": "2024-07-18T16:00:00+00:00",
        "ride for":"someone else",
        "rider_name": "Belle Vue",
        "rider_phone": "6287345655",
    }

    # return data

    try:
        # 1. Create AGI session
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Uber)", **state})
        if not state.get("success"):
            return {'success': False, 'error': 'Failed to create AGI session'}
        
        # 2. Compose ordering instructions using flight details
        message = f"Go to {ENDPOINTS['uber']} and order a Uber ride with these details: {data}"

        # 3. Send ordering request to AGI
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Uber Ordering Task", **state})
        if not state.get("success"):
            return {'success': False, 'error': 'Failed to send task to AGI agent'}
        
        # 4. Wait for completion & collect result
        print("  Waiting for AGI agent to complete Uber ordering...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Uber Ordering", "status": status})
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Uber Ordering Results", **state})
        
        # 5. Parse and return result
        if not data:
            return {'success': False, 'error': 'No results from AGI agent'}
        try:
            if isinstance(data, str):
                data = json.loads(data)
        except Exception as e:
            print(f"  Error parsing AGI response: {e}")
            return {'success': False, 'error': f'Failed to parse response: {e}'}
        if data.get('success'):
            return {
                'success': True,
                'details': data,
                'confirmation_number': data.get('confirmation_number')
            }
        return {'success': False, 'error': data.get('error', 'Ordering failed')}
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Uber)", **cleanup_state})


# step 3: book lodging using AGI
def book_lodging_agi(p, state_log):
    """Book a lodging using the AGI agent. Returns a dict with booking results."""
    session_id = None
    data = {
        # from july 19 2024 to july 21 2024
        "destination": "San Francisco",
        "checkin_date": "2024-07-19",
        "checkout_date": "2024-07-21",
        "firstname": "Belle",
        "lastname": "Vue",
        "email": "belle@vue.com",
        "country": "USA",
        "address": "100 Van Ness",
        "city": "San Francisco",
        "state": "CA",
        "postal_code": "94101",
        "cardholder_name": "Belle Vue",
        "card_number": "1234567890123456",
        "expiration_date": "01/2025",
        "cvv": "123",

    }

    try:
        # 1. Create AGI session
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Lodging)", **state})
        if not state.get("success"):
            return {'success': False, 'error': 'Failed to create AGI session'}
        
        # 2. Compose booking instructions using flight details
        message = f"Go to {ENDPOINTS['marriott']} and book a lodging with these details: {data}"
        # 3. Send booking request to AGI
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Lodging Booking Task", **state})
        if not state.get("success"):
            return {'success': False, 'error': 'Failed to send task to AGI agent'}
        
        # 4. Wait for completion & collect result
        print("  Waiting for AGI agent to complete lodging booking...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Lodging Booking", "status": status})
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Lodging Booking Results", **state})
        
        # 5. Parse and return result
        if not data:
            return {'success': False, 'error': 'No results from AGI agent'}
        try:
            if isinstance(data, str):
                data = json.loads(data)
        except Exception as e:
            print(f"  Error parsing AGI response: {e}")     
            return {'success': False, 'error': f'Failed to parse response: {e}'}
        if data.get('success'):
            return {
                'success': True,
                'details': data,
                'confirmation_number': data.get('confirmation_number')
            }
        return {'success': False, 'error': data.get('error', 'Booking failed')}
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Lodging)", **cleanup_state})
    return data


# step 4: book dining using AGI
def book_dining_agi(p, state_log):
    """Book a dining using the AGI agent. Returns a dict with booking results."""
    session_id = None

    # if eat_mode is in, book dining using doordash, else book dining using opendining
    if p['eat_mode'] == 'in':
        data = {
            ENDPOINTS['doordash']: {
                "cuisine":"asian",
                "restaurant_name":"moonbowls - Healthy Korean Bowls",
                "food":"korean bbq bowl",
                "size":"12oz",
                "preference":"spicy",
            }
        }
    else:   
        data = {
            ENDPOINTS['opendining']: {
                "restaurant_name": "Evening Delight",
                "people": 2,
                "date": "November 24 2025",
                "time": "5:00 PM",
                "phone": "6287345655",
                "email": "belle@vue.com",
                "note": "Dom Pérignon",
            }
        }

    # return data
    try:
        # 1. Create AGI session
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Dining)", **state})
        if not state.get("success"):
            return {'success': False, 'error': 'Failed to create AGI session'}
        
        # 2. Compose booking instructions using flight details
        # go to doordash or opendining based on eat_mode
        if p['eat_mode'] == 'in':
            message = f"Go to {ENDPOINTS['doordash']} and book a dining with these details: {data}"
        else:
            message = f"Go to {ENDPOINTS['opendining']} and book a dining with these details: {data}"

        # 3. Send booking request to AGI
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Dining Booking Task", **state})
        if not state.get("success"):
            return {'success': False, 'error': 'Failed to send task to AGI agent'}
        
        # 4. Wait for completion & collect result
        print("  Waiting for AGI agent to complete dining booking...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Dining Booking", "status": status})
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Dining Booking Results", **state})
        
        # 5. Parse and return result
        if not data:
            return {'success': False, 'error': 'No results from AGI agent'}
        try:
            if isinstance(data, str):
                data = json.loads(data)
        except Exception as e:
            print(f"  Error parsing AGI response: {e}")
            return {'success': False, 'error': f'Failed to parse response: {e}'}
        if data.get('success'):
            return {
                'success': True,
                'details': data,
                'confirmation_number': data.get('confirmation_number')
            }
        return {'success': False, 'error': data.get('error', 'Booking failed')}
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Dining)", **cleanup_state})
    return data


# step 5: book calendar using AGI   
def book_calendar_agi(p, state_log):
    """Book a calendar using the AGI agent. Returns a dict with booking results."""
    session_id = None
    data = {
        "event_name": "Belle Vue Arrival",
        "all-day": True,
        "event_date": "July 19 2024",        
    }
    try:
        # 1. Create AGI session
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Calendar)", **state})
        if not state.get("success"):
            return {'success': False, 'error': 'Failed to create AGI session'}
        
        # 2. Compose booking instructions using flight details
        message = f"Go to {ENDPOINTS['calendar']} and create a new all-day event with these details: {data}"
        # 3. Send booking request to AGI
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Calendar Booking Task", **state})
        if not state.get("success"):
            return {'success': False, 'error': 'Failed to send task to AGI agent'}
        
        # 4. Wait for completion & collect result
        print("  Waiting for AGI agent to complete calendar booking...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Calendar Booking", "status": status})
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Calendar Booking Results", **state})
        
        # 5. Parse and return result
        if not data:
            return {'success': False, 'error': 'No results from AGI agent'}
        try:
            if isinstance(data, str):
                data = json.loads(data)
        except Exception as e:
            print(f"  Error parsing AGI response: {e}")
            return {'success': False, 'error': f'Failed to parse response: {e}'}
        if data.get('success'):
            return {
                'success': True,
                'details': data,
                'confirmation_number': data.get('confirmation_number')
            }
        return {'success': False, 'error': data.get('error', 'Booking failed')}
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Calendar)", **cleanup_state})
    return data

if __name__ == '__main__':
    app.run(debug=True)
