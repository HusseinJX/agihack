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

# Basic HTML UI using render_template_string to keep everything in one file
INDEX_HTML = """
<!doctype html>
<title>Fly-Out Assistant</title>
<h2>Fly someone out — quick workflow</h2>
<form method=post action="/start">
  <label>From (city or airport code): <input name=from_location required></label><br>
  <label>To (city or airport code): <input name=to_location required></label><br>
  <label>Depart date (YYYY-MM-DD): <input name=depart_date required></label><br>
  <label>Return date (optional YYYY-MM-DD): <input name=return_date></label><br>
  <label>Eating preference: 
    <select name=eat_mode>
      <option value="in">Eat in (order food)</option>
      <option value="out">Eat out (book restaurant)</option>
    </select>
  </label><br>
  <label>Lodging preference:
    <select name=lodging>
      <option value="airbnb">Airbnb</option>
      <option value="marriott">Marriott</option>
    </select>
  </label><br>
  <label>Number of travelers: <input name=num_travelers type=number min=1 value=1></label><br>
  <button type=submit>Start Fly-Out Workflow</button>
</form>

<p>Note: This is a demo. Remote endpoints are example placeholders — adapt to your real APIs.</p>
"""

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)


@app.route('/start', methods=['POST'])
def start_workflow():
    print("\n=== Starting Fly-Out Workflow ===")
    data = request.form.to_dict()
    print(f"Received data: {data}")
    
    # parse and validate inputs
    try:
        depart_date = datetime.datetime.strptime(data.get('depart_date'), '%Y-%m-%d').date()
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
        'to': data.get('to_location'),
        'depart_date': str(depart_date),
        'return_date': str(return_date) if return_date else None,
        'eat_mode': data.get('eat_mode'),
        'lodging': data.get('lodging'),
        'num_travelers': int(data.get('num_travelers', 1)),
    }
    
    print(f"Workflow payload: {workflow_payload}")

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

def wait_for_agi_completion(session_id, max_attempts=30, delay=2):
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

    # 2) Order Uber using AGI
    print("\n[Step 2/5] Using AGI agent to order Uber...")
    if flight_resp.get('success') and flight_resp.get('arrival_time'):
        arrival_time_iso = flight_resp.get('arrival_time')
        try:
            eta = datetime.datetime.fromisoformat(arrival_time_iso)
        except Exception as e:
            print(f"Warning: Could not parse arrival_time '{arrival_time_iso}': {e}")
            eta = None
        uber_resp = order_uber_agi(p, eta, state_log)
    else:
        print("Skipping Uber order due to flight failure")
        uber_resp = {'success': False, 'error': 'Skipped due to flight failure'}
    print(f"Uber result: {uber_resp}")
    timeline.append({'step': 'order_uber', 'result': uber_resp})

    # 3) Dining or Food order using AGI
    print(f"\n[Step 3/5] Using AGI agent for dining (mode: {p.get('eat_mode')})...")
    if p.get('eat_mode') == 'out':
        dine_resp = book_opendining_agi(p, flight_resp, state_log)
    else:
        dine_resp = order_doordash_agi(p, flight_resp, state_log)
    print(f"Dining result: {dine_resp}")
    timeline.append({'step': 'dining', 'result': dine_resp})

    # 4) Book lodging using AGI
    print(f"\n[Step 4/5] Using AGI agent to book lodging ({p.get('lodging')})...")
    lodging_resp = book_lodging_agi(p, state_log)
    print(f"Lodging result: {lodging_resp}")
    timeline.append({'step': 'lodging', 'result': lodging_resp})

    # 5) Add to calendar using AGI
    print("\n[Step 5/5] Using AGI agent to add to calendar...")
    calendar_resp = add_to_calendar_agi(p, flight_resp, lodging_resp, state_log)
    print(f"Calendar result: {calendar_resp}")
    timeline.append({'step': 'calendar', 'result': calendar_resp})

    result = {
        'workflow_id': f"wf_{int(time.time())}",
        'submitted': datetime.datetime.utcnow().isoformat() + 'Z',
        'timeline': timeline,
        'state_log': state_log,
    }
    print("\n=== Workflow Complete ===")
    return result


# 1) Buy flight using AGI
def buy_flight_agi(p, state_log):
    """Use AGI agent to book a flight"""
    session_id = None
    try:
        # Create AGI session
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Flight)", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to create AGI session'}
        
        # Send task to AGI agent with clear, specific instructions
        message = f"""
Go to {ENDPOINTS['flight']} and book a flight with the following details:

- From: {p['from']}
- To: {p['to']}
- Departure date: {p['depart_date']}
- Number of passengers: {p['num_travelers']}

Complete the booking process and extract the following information:

1. Booking confirmation number
2. Departure time (ISO format)
3. Arrival time (ISO format)
4. Flight number
5. Total price
6. Booking status (confirmed/pending/failed)

Return the result as JSON in this exact format:

{{
    "success": true,
    "confirmation_number": "ABC123",
    "departure_time": "2024-01-15T08:00:00Z",
    "arrival_time": "2024-01-15T11:30:00Z",
    "flight_number": "UA123",
    "price": 299.99,
    "status": "confirmed",
    "details": {{}}
}}

If booking fails or the service is unavailable:
- Set "success": false
- Include "error": "description of what went wrong"
- Still return valid JSON

Return ONLY valid JSON, no markdown formatting or explanations.
"""
        
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Flight Booking Task", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to send task to AGI agent'}
        
        # Wait for completion
        print("  Waiting for AGI agent to complete flight booking...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Flight Booking", "status": status})
        
        # Get results
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Flight Booking Results", **state})
        
        # Parse results
        if data:
            try:
                if isinstance(data, str):
                    data = json.loads(data)
                if data.get('success'):
                    return {
                        'success': True,
                        'details': data,
                        'arrival_time': data.get('arrival_time'),
                        'confirmation_number': data.get('confirmation_number')
                    }
                else:
                    return {'success': False, 'error': data.get('error', 'Booking failed')}
            except Exception as e:
                print(f"  Error parsing AGI response: {e}")
                return {'success': False, 'error': f'Failed to parse response: {str(e)}'}
        else:
            return {'success': False, 'error': 'No results from AGI agent'}
    
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Flight)", **cleanup_state})


# 2) Order Uber using AGI
def order_uber_agi(p, arrival_dt=None, state_log=None):
    """Use AGI agent to order an Uber ride"""
    if state_log is None:
        state_log = []
    
    # Calculate scheduled time
    if arrival_dt:
        scheduled_time = (arrival_dt + datetime.timedelta(minutes=15)).isoformat()
    else:
        scheduled_time = p['depart_date'] + 'T18:30:00'
    
    session_id = None
    try:
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Uber)", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to create AGI session'}
        
        message = f"""
Go to {ENDPOINTS['uber']} and order an Uber ride with these details:

- Pickup location: airport
- Dropoff location: guest_address_placeholder
- Scheduled time: {scheduled_time}
- Number of riders: {p['num_travelers']}

Complete the order and extract:

1. Order confirmation number
2. Estimated pickup time
3. Estimated arrival time
4. Driver name (if available)
5. Vehicle type
6. Total fare
7. Order status

Return as JSON:

{{
    "success": true,
    "confirmation_number": "UBER123",
    "pickup_time": "2024-01-15T11:45:00Z",
    "estimated_arrival": "2024-01-15T12:30:00Z",
    "driver_name": "John D.",
    "vehicle_type": "UberX",
    "fare": 25.50,
    "status": "confirmed"
}}

If order fails, set "success": false and include error message.
Return ONLY valid JSON.
"""
        
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Uber Order Task", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to send task to AGI agent'}
        
        print("  Waiting for AGI agent to complete Uber order...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Uber Order", "status": status})
        
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Uber Order Results", **state})
        
        if data:
            try:
                if isinstance(data, str):
                    data = json.loads(data)
                if data.get('success'):
                    return {'success': True, 'details': data}
                else:
                    return {'success': False, 'error': data.get('error', 'Order failed')}
            except Exception as e:
                return {'success': False, 'error': f'Failed to parse response: {str(e)}'}
        else:
            return {'success': False, 'error': 'No results from AGI agent'}
    
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Uber)", **cleanup_state})


# 3a) Book OpenDining using AGI
def book_opendining_agi(p, flight_resp, state_log=None):
    """Use AGI agent to book a restaurant reservation"""
    if state_log is None:
        state_log = []
    
    # Calculate preferred time
    if flight_resp.get('arrival_time'):
        try:
            arrival = datetime.datetime.fromisoformat(flight_resp.get('arrival_time'))
            preferred_time = (arrival + datetime.timedelta(hours=1)).isoformat()
        except Exception:
            preferred_time = p['depart_date'] + 'T19:00:00'
    else:
        preferred_time = p['depart_date'] + 'T19:00:00'
    
    session_id = None
    try:
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Dining)", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to create AGI session'}
        
        message = f"""
Go to {ENDPOINTS['opendining']} and book a restaurant reservation:

- Party size: {p['num_travelers']}
- Date and time: {preferred_time}
- Special notes: Guest arriving by plane; please seat promptly.

Complete the reservation and extract:

1. Reservation confirmation number
2. Restaurant name
3. Reservation time
4. Table number (if available)
5. Status (confirmed/pending)

Return as JSON:

{{
    "success": true,
    "confirmation_number": "RES456",
    "restaurant_name": "Fine Dining",
    "reservation_time": "{preferred_time}",
    "table_number": "12",
    "status": "confirmed"
}}

If booking fails, set "success": false with error details.
Return ONLY valid JSON.
"""
        
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Dining Reservation Task", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to send task to AGI agent'}
        
        print("  Waiting for AGI agent to complete dining reservation...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Dining Reservation", "status": status})
        
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Dining Reservation Results", **state})
        
        if data:
            try:
                if isinstance(data, str):
                    data = json.loads(data)
                if data.get('success'):
                    return {'success': True, 'details': data}
                else:
                    return {'success': False, 'error': data.get('error', 'Reservation failed')}
            except Exception as e:
                return {'success': False, 'error': f'Failed to parse response: {str(e)}'}
        else:
            return {'success': False, 'error': 'No results from AGI agent'}
    
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Dining)", **cleanup_state})


# 3b) Order DoorDash using AGI
def order_doordash_agi(p, flight_resp, state_log=None):
    """Use AGI agent to order food delivery"""
    if state_log is None:
        state_log = []
    
    # Calculate delivery time
    if flight_resp.get('arrival_time'):
        try:
            arrival = datetime.datetime.fromisoformat(flight_resp.get('arrival_time'))
            delivery_time = (arrival + datetime.timedelta(minutes=45)).isoformat()
        except Exception:
            delivery_time = p['depart_date'] + 'T20:00:00'
    else:
        delivery_time = p['depart_date'] + 'T20:00:00'
    
    session_id = None
    try:
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Food Delivery)", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to create AGI session'}
        
        message = f"""
Go to {ENDPOINTS['doordash']} and place a food delivery order:

- Delivery address: guest_address_placeholder
- Delivery time: {delivery_time}
- Items to order: dinner_box, bottle_of_wine

Complete the order and extract:

1. Order confirmation number
2. Estimated delivery time
3. Restaurant name
4. Total price
5. Order status

Return as JSON:

{{
    "success": true,
    "confirmation_number": "DD789",
    "estimated_delivery": "{delivery_time}",
    "restaurant_name": "Local Restaurant",
    "total_price": 45.99,
    "status": "confirmed"
}}

If order fails, set "success": false with error message.
Return ONLY valid JSON.
"""
        
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Food Order Task", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to send task to AGI agent'}
        
        print("  Waiting for AGI agent to complete food order...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Food Order", "status": status})
        
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Food Order Results", **state})
        
        if data:
            try:
                if isinstance(data, str):
                    data = json.loads(data)
                if data.get('success'):
                    return {'success': True, 'details': data}
                else:
                    return {'success': False, 'error': data.get('error', 'Order failed')}
            except Exception as e:
                return {'success': False, 'error': f'Failed to parse response: {str(e)}'}
        else:
            return {'success': False, 'error': 'No results from AGI agent'}
    
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Food Delivery)", **cleanup_state})


# 4) Book lodging using AGI
def book_lodging_agi(p, state_log=None):
    """Use AGI agent to book lodging"""
    if state_log is None:
        state_log = []
    
    provider = p.get('lodging')
    url = ENDPOINTS['airbnb'] if provider == 'airbnb' else ENDPOINTS['marriott']
    checkout_date = p['return_date'] or (datetime.date.fromisoformat(p['depart_date']) + datetime.timedelta(days=2)).isoformat()
    
    session_id = None
    try:
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Lodging)", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to create AGI session'}
        
        message = f"""
Go to {url} and book {provider} accommodation:

- City: {p['to']}
- Check-in date: {p['depart_date']}
- Check-out date: {checkout_date}
- Number of guests: {p['num_travelers']}

Complete the booking and extract:

1. Booking confirmation number
2. Property name/address
3. Check-in time
4. Check-out time
5. Total price
6. Booking status

Return as JSON:

{{
    "success": true,
    "confirmation_number": "LODGING123",
    "property_name": "Cozy Apartment",
    "checkin_time": "{p['depart_date']}T15:00:00Z",
    "checkout_time": "{checkout_date}T11:00:00Z",
    "total_price": 250.00,
    "status": "confirmed"
}}

If booking fails, set "success": false with error details.
Return ONLY valid JSON.
"""
        
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Lodging Booking Task", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to send task to AGI agent'}
        
        print(f"  Waiting for AGI agent to complete {provider} booking...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Lodging Booking", "status": status})
        
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Lodging Booking Results", **state})
        
        if data:
            try:
                if isinstance(data, str):
                    data = json.loads(data)
                if data.get('success'):
                    return {'success': True, 'details': data}
                else:
                    return {'success': False, 'error': data.get('error', 'Booking failed')}
            except Exception as e:
                return {'success': False, 'error': f'Failed to parse response: {str(e)}'}
        else:
            return {'success': False, 'error': 'No results from AGI agent'}
    
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Lodging)", **cleanup_state})


# 5) Add to calendar using AGI
def add_to_calendar_agi(p, flight_resp, lodging_resp, state_log=None):
    """Use AGI agent to add events to calendar"""
    if state_log is None:
        state_log = []
    
    # Prepare events data
    events = []
    if flight_resp.get('success'):
        flight_details = flight_resp.get('details', {})
        events.append({
            'title': f"Flight {p['from']} → {p['to']}",
            'start': flight_details.get('departure_time', p['depart_date'] + 'T08:00:00'),
            'end': flight_details.get('arrival_time', p['depart_date'] + 'T12:00:00'),
            'description': 'Auto-booked flight'
        })

    if lodging_resp.get('success'):
        checkout_date = p['return_date'] or (datetime.date.fromisoformat(p['depart_date']) + datetime.timedelta(days=2)).isoformat()
        events.append({
            'title': f"Stay: {p['lodging']}",
            'start': p['depart_date'],
            'end': checkout_date,
            'description': 'Auto-booked lodging'
        })

    if not events:
        print("  Warning: No events to add to calendar")
        return {'success': False, 'error': 'No events to add'}

    session_id = None
    try:
        session_id, state = create_agi_session()
        state_log.append({"step": "Create Session (Calendar)", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to create AGI session'}
        
        events_json = json.dumps(events, indent=2)
        
        message = f"""
Go to {ENDPOINTS['calendar']} and add the following events to the calendar:

{events_json}

Add all events and extract:

1. Calendar confirmation
2. Number of events added
3. Event IDs (if available)
4. Status

Return as JSON:

{{
    "success": true,
    "events_added": {len(events)},
    "event_ids": ["evt1", "evt2"],
    "status": "confirmed"
}}

If adding events fails, set "success": false with error message.
Return ONLY valid JSON.
"""
        
        _, state = send_agi_message(session_id, message)
        state_log.append({"step": "Send Calendar Task", **state})
        if not state["success"]:
            return {'success': False, 'error': 'Failed to send task to AGI agent'}
        
        print("  Waiting for AGI agent to add calendar events...")
        status = wait_for_agi_completion(session_id)
        state_log.append({"step": "Wait for Calendar Update", "status": status})
        
        data, state = get_agi_results(session_id)
        state_log.append({"step": "Get Calendar Results", **state})
        
        if data:
            try:
                if isinstance(data, str):
                    data = json.loads(data)
                if data.get('success'):
                    return {'success': True, 'details': data}
                else:
                    return {'success': False, 'error': data.get('error', 'Calendar update failed')}
            except Exception as e:
                return {'success': False, 'error': f'Failed to parse response: {str(e)}'}
        else:
            return {'success': False, 'error': 'No results from AGI agent'}
    
    finally:
        if session_id:
            cleanup_state = cleanup_agi_session(session_id)
            state_log.append({"step": "Cleanup Session (Calendar)", **cleanup_state})


if __name__ == '__main__':
    app.run(debug=True)
