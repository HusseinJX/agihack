import React, { useState } from "react";

// Single-file React + Tailwind app that orchestrates booking a flight, rides, food, stay, and calendar
// - Uses the provided endpoints (real-flyunified, real-udriver, real-opendining, real-dashdish, real-staynb, real-marrisuite, real-gocalendar)
// - Includes detailed UI, validation, sequential workflow, retries, and clear JSON logs
// - Replace AGI_BASE_URL, AGI_API_KEY with your real AGI endpoint and key if you want the AGI orchestration step

const AGI_BASE_URL = "https://api.agi.tech/v1"; // <-- replace if you use AGI
const AGI_API_KEY = "49e851f1-8f2b-4565-9995-136ec665691a";

export default function FlyOutApp() {
  const [origin, setOrigin] = useState("");
  const [departureDate, setDepartureDate] = useState("");
  const [eatOption, setEatOption] = useState("in"); // "in" or "out"
  const [accommodation, setAccommodation] = useState("airbnb"); // "airbnb" or "marriott"
  const [guestName, setGuestName] = useState("");
  const [statusSteps, setStatusSteps] = useState([]);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState({});

  function pushStep(step) {
    setStatusSteps((s) => [...s, { time: new Date().toISOString(), ...step }]);
  }

  async function safePostJson(url, body, opts = {}) {
    // Basic fetch wrapper with JSON and retries
    const maxRetries = opts.retries ?? 1;
    let lastErr;
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const text = await res.text();
        try {
          return { ok: res.ok, status: res.status, json: JSON.parse(text), text };
        } catch (e) {
          return { ok: res.ok, status: res.status, json: null, text };
        }
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr;
  }

  function validate() {
    if (!origin) return "Origin is required";
    if (!departureDate) return "Departure date is required";
    if (!guestName) return "Guest name is required";
    return null;
  }

  async function orchestrate(e) {
    e?.preventDefault();
    const invalid = validate();
    if (invalid) return pushStep({ type: "error", message: invalid });

    setStatusSteps([]);
    setResults({});
    setRunning(true);

    try {
      pushStep({ type: "info", message: "Starting orchestration" });

      // Step 1: Buy flight
      pushStep({ type: "action", message: "Buying flight on real-flyunified" });
      const flightPayload = {
        guestName,
        from: origin,
        departureDate,
        seatClass: "economy",
        note: "Auto-booked by orchestration app",
      };

      const flightResp = await safePostJson("https://real-flyunified.vercel.app/api/book", flightPayload, { retries: 2 });
      pushStep({ type: flightResp.ok ? "success" : "error", message: "Flight response", detail: flightResp });
      if (!flightResp.ok) throw new Error(`Flight booking failed: ${flightResp.status}`);

      // Attempt to derive an arrival time from the response, fallback to departureDate + 3h
      let arrivalISO = (flightResp.json && flightResp.json.arrival_time) || null;
      if (!arrivalISO) {
        const dep = new Date(departureDate);
        dep.setHours(dep.getHours() + 3);
        arrivalISO = dep.toISOString();
        pushStep({ type: "warn", message: "Arrival time not provided by flight API, using departureDate + 3h" });
      }

      setResults((r) => ({ ...r, flight: flightResp.json || flightResp.text }));

      // Step 2: Order Uber from airport to your place
      pushStep({ type: "action", message: "Ordering Uber on real-udriver" });
      // schedule pickup slightly after arrival
      const pickupTime = new Date(arrivalISO);
      pickupTime.setMinutes(pickupTime.getMinutes() + 15);

      const uberPayload = {
        guestName,
        pickup: "airport",
        pickup_time: pickupTime.toISOString(),
        dropoff: "guest_place",
        note: "Ride ordered after flight arrival",
      };

      const uberResp = await safePostJson("https://real-udriver.vercel.app/api/order", uberPayload, { retries: 2 });
      pushStep({ type: uberResp.ok ? "success" : "error", message: "Uber response", detail: uberResp });
      if (!uberResp.ok) throw new Error(`Uber ordering failed: ${uberResp.status}`);
      setResults((r) => ({ ...r, uber: uberResp.json || uberResp.text }));

      // Step 3: Food - either book table (opendining) or order doordash
      if (eatOption === "in") {
        pushStep({ type: "action", message: "Booking a table on real-opendining" });
        const diningPayload = {
          guestName,
          time: new Date(pickupTime.getTime() + 30 * 60000).toISOString(), // 30 min after dropoff
          party_size: 2,
          note: "Auto-booked table",
        };
        const dinResp = await safePostJson("https://real-opendining.vercel.app/api/reserve", diningPayload, { retries: 2 });
        pushStep({ type: dinResp.ok ? "success" : "error", message: "Dining response", detail: dinResp });
        if (!dinResp.ok) throw new Error(`Dining booking failed: ${dinResp.status}`);
        setResults((r) => ({ ...r, dining: dinResp.json || dinResp.text }));
      } else {
        pushStep({ type: "action", message: "Ordering food on real-dashdish (DoorDash)" });
        const foodPayload = {
          guestName,
          delivery_time: new Date(pickupTime.getTime() + 45 * 60000).toISOString(),
          items: ["chef_recommendation", "wine"],
          note: "Auto-order from orchestration app",
        };
        const foodResp = await safePostJson("https://real-dashdish.vercel.app/api/order", foodPayload, { retries: 2 });
        pushStep({ type: foodResp.ok ? "success" : "error", message: "Food order response", detail: foodResp });
        if (!foodResp.ok) throw new Error(`Food ordering failed: ${foodResp.status}`);
        setResults((r) => ({ ...r, food: foodResp.json || foodResp.text }));
      }

      // Step 4: Book accommodation (Airbnb or Marriott)
      if (accommodation === "airbnb") {
        pushStep({ type: "action", message: "Booking Airbnb on real-staynb" });
        const stayPayload = {
          guestName,
          checkin: departureDate,
          checkout: new Date(new Date(departureDate).getTime() + 2 * 24 * 3600 * 1000).toISOString(), // 2 nights default
          property_type: "entire_place",
        };
        const stayResp = await safePostJson("https://real-staynb.vercel.app/api/book", stayPayload, { retries: 2 });
        pushStep({ type: stayResp.ok ? "success" : "error", message: "Stay response", detail: stayResp });
        if (!stayResp.ok) throw new Error(`Stay booking failed: ${stayResp.status}`);
        setResults((r) => ({ ...r, stay: stayResp.json || stayResp.text }));
      } else {
        pushStep({ type: "action", message: "Booking Marriott on real-marrisuite" });
        const marPayload = {
          guestName,
          checkin: departureDate,
          nights: 2,
          room_type: "standard",
        };
        const marResp = await safePostJson("https://real-marrisuite.vercel.app/api/reserve", marPayload, { retries: 2 });
        pushStep({ type: marResp.ok ? "success" : "error", message: "Marriott response", detail: marResp });
        if (!marResp.ok) throw new Error(`Marriott booking failed: ${marResp.status}`);
        setResults((r) => ({ ...r, marriott: marResp.json || marResp.text }));
      }

      // Step 5: Add days to calendar
      pushStep({ type: "action", message: "Adding events to GoCalendar" });
      const calendarPayload = {
        guestName,
        events: [
          { title: "Flight", date: departureDate, note: "Arrival/Departure" },
          { title: "Stay", date: departureDate, note: "Accommodation reserved" },
        ],
      };
      const calResp = await safePostJson("https://real-gocalendar.vercel.app/calendar/api/add", calendarPayload, { retries: 2 });
      pushStep({ type: calResp.ok ? "success" : "error", message: "Calendar response", detail: calResp });
      if (!calResp.ok) throw new Error(`Calendar update failed: ${calResp.status}`);
      setResults((r) => ({ ...r, calendar: calResp.json || calResp.text }));

      // Optional Step 6: Notify AGI to summarize the itinerary (if configured)
      if (AGI_API_KEY && AGI_API_KEY !== "REPLACE_WITH_KEY") {
        pushStep({ type: "action", message: "Sending itinerary summary to AGI" });
        try {
          const agiResp = await safePostJson(`${AGI_BASE_URL}/sessions`, {
            api_key: AGI_API_KEY,
            message: `Create a traveler-friendly itinerary summary for ${guestName} from ${origin} on ${departureDate}. Results: ${JSON.stringify(
              results
            )}`,
          });
          pushStep({ type: agiResp.ok ? "success" : "warn", message: "AGI response", detail: agiResp });
          setResults((r) => ({ ...r, agi: agiResp.json || agiResp.text }));
        } catch (e) {
          pushStep({ type: "warn", message: "AGI call failed, continuing without AGI" });
        }
      }

      pushStep({ type: "done", message: "Orchestration complete" });
    } catch (err) {
      pushStep({ type: "fatal", message: "Orchestration failed", detail: err.message || String(err) });
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 p-6">
      <div className="max-w-3xl mx-auto bg-gray-800 rounded-2xl p-6 shadow-lg">
        <h1 className="text-2xl font-bold mb-4">Fly-Out Orchestrator</h1>
        <form onSubmit={orchestrate} className="space-y-4">
          <label className="block">
            <div className="text-sm text-gray-300">Guest name</div>
            <input value={guestName} onChange={(e) => setGuestName(e.target.value)} className="w-full mt-1 p-2 rounded bg-gray-900 border border-gray-700" placeholder="e.g. Jordan" />
          </label>

          <label className="block">
            <div className="text-sm text-gray-300">From (airport/city)</div>
            <input value={origin} onChange={(e) => setOrigin(e.target.value)} className="w-full mt-1 p-2 rounded bg-gray-900 border border-gray-700" placeholder="SFO" />
          </label>

          <label className="block">
            <div className="text-sm text-gray-300">Departure date & time</div>
            <input type="datetime-local" value={departureDate} onChange={(e) => setDepartureDate(e.target.value)} className="w-full mt-1 p-2 rounded bg-gray-900 border border-gray-700" />
          </label>

          <div className="grid grid-cols-2 gap-4">
            <label className="block">
              <div className="text-sm text-gray-300">Eat</div>
              <select value={eatOption} onChange={(e) => setEatOption(e.target.value)} className="w-full mt-1 p-2 rounded bg-gray-900 border border-gray-700">
                <option value="in">Eat in (book table)</option>
                <option value="out">Eat out (order DoorDash)</option>
              </select>
            </label>

            <label className="block">
              <div className="text-sm text-gray-300">Accommodation</div>
              <select value={accommodation} onChange={(e) => setAccommodation(e.target.value)} className="w-full mt-1 p-2 rounded bg-gray-900 border border-gray-700">
                <option value="airbnb">Airbnb</option>
                <option value="marriott">Marriott</option>
              </select>
            </label>
          </div>

          <div className="flex gap-3">
            <button disabled={running} type="submit" className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50">Start Orchestration</button>
            <button type="button" disabled={running} onClick={() => { setOrigin(""); setDepartureDate(""); setGuestName(""); setStatusSteps([]); setResults({}); }} className="px-4 py-2 rounded bg-gray-700">Reset</button>
          </div>
        </form>

        <div className="mt-6">
          <h2 className="text-lg font-semibold">Status</h2>
          <div className="mt-2 bg-gray-900 p-3 rounded max-h-64 overflow-auto">
            {statusSteps.length === 0 && <div className="text-gray-400">No actions yet.</div>}
            {statusSteps.map((s, i) => (
              <div key={i} className="mb-2">
                <div className="text-xs text-gray-500">{new Date(s.time).toLocaleString()}</div>
                <div className={`text-sm ${s.type === 'error' || s.type === 'fatal' ? 'text-rose-400' : s.type === 'warn' ? 'text-yellow-300' : 'text-green-300'}`}>{s.message}</div>
                {s.detail && <pre className="text-xs text-gray-400 mt-1 whitespace-pre-wrap">{JSON.stringify(s.detail, null, 2)}</pre>}
              </div>
            ))}
          </div>
        </div>

        <div className="mt-6">
          <h2 className="text-lg font-semibold">Results (raw)</h2>
          <pre className="mt-2 bg-gray-900 p-3 rounded max-h-64 overflow-auto text-xs">{JSON.stringify(results, null, 2)}</pre>
        </div>
      </div>

      <footer className="max-w-3xl mx-auto text-center mt-6 text-sm text-gray-500">This is a demo orchestrator — replace API endpoints and payloads with the real provider contracts before production use.</footer>
    </div>
  );
}
