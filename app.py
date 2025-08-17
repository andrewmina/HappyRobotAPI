import os, json, sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Literal
from fastapi import FastAPI, Header, HTTPException, Request, Query
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
from azure.data.tables import TableServiceClient
import uuid

API_KEY = os.getenv("API_KEY", "")
DB_PATH = os.getenv("DB_PATH", "calls.db")

app = FastAPI(title="Inbound Carrier Sales API")

# ---------- Security ----------
def require_api_key(x_api_key: str | None):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

# ---------- Data ----------
with open("loads.json") as f:
    LOADS = json.load(f)

# ---------- DB ----------
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_id TEXT,
            timestamp TEXT,
            outcome TEXT,
            sentiment TEXT,
            rounds INTEGER,
            mc TEXT, dot TEXT, legal_name TEXT,
            selected_load_id TEXT,
            origin TEXT, destination TEXT,
            pickup_datetime TEXT, delivery_datetime TEXT,
            equipment_type TEXT, miles INTEGER,
            loadboard_rate REAL, agreed_rate REAL,
            transcript TEXT
        )
    """)
    con.commit(); con.close()
init_db()

# ---------- Schemas ----------
class SearchCriteria(BaseModel):
    origin: Dict[str, Any]
    destination: Dict[str, Any]
    pickup_window_start: str
    pickup_window_end: str
    equipment_type: str

# ---------- Helpers ----------
def city(s: str) -> str:
    return s.split(",")[0].strip().lower()

def score(load: dict, crit: SearchCriteria) -> int:
    s = 0
    if load["equipment_type"].lower() == crit.equipment_type.lower(): s += 5
    if city(load["origin"]) == city(crit.origin["city_state"]): s += 3
    if city(load["destination"]) == city(crit.destination["city_state"]): s += 3
    ld = datetime.fromisoformat(load["pickup_datetime"])
    w0 = datetime.fromisoformat(crit.pickup_window_start)
    w1 = datetime.fromisoformat(crit.pickup_window_end)
    if w0 <= ld <= w1: s += 2
    if load.get("miles", 99999) <= 750: s += 1
    return s

# ---------- Endpoints ----------
@app.get("/health")
def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}

@app.post("/search_loads")
def search_loads(crit: SearchCriteria, x_api_key: str | None = Header(None)):
    require_api_key(x_api_key)
    ranked = sorted(LOADS, key=lambda L: score(L, crit), reverse=True)
    return {"loads": ranked[:3]}

class CounterOffer(BaseModel):
    load_id: str
    carrier_offer: float
    round_num: int


class AddHoursIn(BaseModel):
    datetime_str: str
    hours: int = 10

@app.post("/add-hours")
def add_hours(payload: AddHoursIn, x_api_key: str | None = Header(None)):
    require_api_key(x_api_key)
    try:
        dt = datetime.fromisoformat(payload.datetime_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid datetime format. Use ISO 8601, e.g. 2025-08-16T06:00:00-05:00")
    new_dt = dt + timedelta(hours=payload.hours)
    return {
        "original_datetime": dt.isoformat(),
        "new_datetime": new_dt.isoformat(),
        "hours_added": payload.hours
    }


@app.post("/evaluate_counter")
async def evaluate_counter(data: CounterOffer, x_api_key: str | None = Header(None)):
    require_api_key(x_api_key)
    
    # Get load details
    load = next(L for L in LOADS if L["load_id"] == data.load_id)
    lb = float(load["loadboard_rate"])

    # Calculate negotiation ceiling
    max_bump = lb * 0.12
    pickup = datetime.fromisoformat(load["pickup_datetime"])
    now = datetime.now(pickup.tzinfo)
    if (pickup - now).total_seconds() <= 12 * 3600:
        max_bump += lb * 0.05

    ceiling = lb + max_bump

    # Decide
    if data.carrier_offer <= lb:
        decision = "accept"
        reason = "At or below listed rate — good margin."
    elif data.carrier_offer <= ceiling:
        decision = "accept"
        reason = "Slightly above listed rate but within allowed bump."
    else:
        # Counter logic by round
        if data.round_num == 1:
            decision = "counter"
            broker_offer = lb
        elif data.round_num == 2:
            decision = "counter"
            broker_offer = min(ceiling, lb * 1.05)
        elif data.round_num == 3:
            decision = "counter"
            broker_offer = min(ceiling, lb * 1.08)
        else:
            decision = "reject"
            broker_offer = lb
        return {
            "decision": decision,
            "broker_offer": round(broker_offer, 2),
            "ceiling": round(ceiling, 2),
            "listed_rate": lb,
            "reason": "Counter offer above acceptable ceiling."
        }

    return {
        "decision": decision,
        "broker_offer": round(data.carrier_offer, 2),
        "ceiling": round(ceiling, 2),
        "listed_rate": lb,
        "reason": reason
    }


# Setup Table client
table_service = TableServiceClient.from_connection_string(os.getenv("TABLES_CONN_STRING"))
table_client = table_service.get_table_client(table_name=os.getenv("TABLE_NAME", "calls"))

@app.post("/log_call")
async def log_call(request: Request, x_api_key: str | None = Header(None)):
    require_api_key(x_api_key)
    body = await request.json()
    ext = body.get("extracted", {}) or {}

    # -------------------------
    # 1) Write to Azure Table Storage
    # -------------------------
    entity = {
        "PartitionKey": "CallLogs",
        "RowKey": str(uuid.uuid4()),  # unique ID
        "call_id": body.get("call_id"),
        "timestamp": body.get("timestamp"),
        "outcome": body.get("outcome"),
        "sentiment": body.get("sentiment"),
        "rounds": ext.get("rounds"),
        "mc": ext.get("mc"),
        "dot": ext.get("dot"),
        "legal_name": ext.get("legal_name"),
        "selected_load_id": ext.get("selected_load_id"),
        "origin": ext.get("origin"),
        "destination": ext.get("destination"),
        "pickup_datetime": ext.get("pickup_datetime"),
        "delivery_datetime": ext.get("delivery_datetime"),
        "equipment_type": ext.get("equipment_type"),
        "miles": ext.get("miles"),
        "loadboard_rate": ext.get("loadboard_rate"),
        "agreed_rate": ext.get("agreed_rate"),
        "transcript": body.get("transcript"),
    }
    try:
        table_client.create_entity(entity=entity)
    except Exception as e:
        print("Azure Table insert failed:", e)

    # -------------------------
    # 2) Write to SQLite (for metrics.json)
    # -------------------------
    con = db()
    try:
        con.execute("""
            INSERT INTO calls (
                call_id, timestamp, outcome, sentiment, rounds, mc, dot, legal_name,
                selected_load_id, origin, destination, pickup_datetime, delivery_datetime,
                equipment_type, miles, loadboard_rate, agreed_rate, transcript
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            body.get("call_id"), body.get("timestamp"), body.get("outcome"),
            body.get("sentiment"), ext.get("rounds"), ext.get("mc"), ext.get("dot"),
            ext.get("legal_name"), ext.get("selected_load_id"), ext.get("origin"),
            ext.get("destination"), ext.get("pickup_datetime"), ext.get("delivery_datetime"),
            ext.get("equipment_type"), ext.get("miles"), ext.get("loadboard_rate"),
            ext.get("agreed_rate"), body.get("transcript")
        ))
        con.commit()
    except Exception as e:
        print("SQLite insert failed:", e)
    finally:
        con.close()

    return {"stored": True}


@app.get("/metrics.json")
def metrics_json():
    con = db()
    # simple aggregates
    rows = con.execute("SELECT outcome, COUNT(*) c FROM calls GROUP BY outcome").fetchall()
    by_outcome = {r["outcome"] or "unknown": r["c"] for r in rows}
    rows = con.execute("SELECT sentiment, COUNT(*) c FROM calls GROUP BY sentiment").fetchall()
    by_sentiment = {r["sentiment"] or "unknown": r["c"] for r in rows}
    rows = con.execute("""
        SELECT substr(timestamp,1,10) d, COUNT(*) c,
               SUM(CASE WHEN outcome='agreed_and_transferred' THEN 1 ELSE 0 END) won
        FROM calls GROUP BY d ORDER BY d
    """).fetchall()
    daily = [{"date": r["d"], "calls": r["c"], "wins": r["won"]} for r in rows]
    rows = con.execute("""
        SELECT equipment_type et, COUNT(*) c FROM calls WHERE equipment_type IS NOT NULL GROUP BY et
    """).fetchall()
    by_equipment = {r["et"]: r["c"] for r in rows}
    rows = con.execute("""
        SELECT AVG(agreed_rate - loadboard_rate) diff FROM calls 
        WHERE agreed_rate IS NOT NULL AND loadboard_rate IS NOT NULL
    """).fetchone()
    avg_delta = rows["diff"] if rows and rows["diff"] is not None else 0.0
    con.close()
    return {"by_outcome": by_outcome, "by_sentiment": by_sentiment,
            "daily": daily, "by_equipment": by_equipment, "avg_rate_delta": round(avg_delta,2)}

# lightweight HTML dashboard
DASH_HTML = """
<!doctype html><meta charset="utf-8"><title>Inbound Carrier Sales Dashboard</title>
<h2>Inbound Carrier Sales — Live Metrics</h2>
<div><canvas id="c1" width="600" height="260"></canvas></div>
<div><canvas id="c2" width="600" height="260"></canvas></div>
<div><canvas id="c3" width="600" height="260"></canvas></div>
<p>Avg agreed - listed delta: <span id="delta"></span></p>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
async function load(){
  const r = await fetch('/metrics.json'); const m = await r.json();
  document.getElementById('delta').textContent = '$' + m.avg_rate_delta;
  // daily
  new Chart(document.getElementById('c1'), {
    type: 'line', data: { labels: m.daily.map(x=>x.date),
    datasets: [{ label:'Calls', data:m.daily.map(x=>x.calls) },
               { label:'Wins', data:m.daily.map(x=>x.wins) }] }
  });
  // by outcome
  new Chart(document.getElementById('c2'), {
    type: 'bar', data: { labels: Object.keys(m.by_outcome),
    datasets: [{ label:'Calls', data:Object.values(m.by_outcome) }] }
  });
  // by sentiment
  new Chart(document.getElementById('c3'), {
    type: 'bar', data: { labels: Object.keys(m.by_sentiment),
    datasets: [{ label:'Calls', data:Object.values(m.by_sentiment) }] }
  });
}
load();
</script>
"""
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return DASH_HTML
