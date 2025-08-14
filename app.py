import os, json, sqlite3
from datetime import datetime, timezone
from typing import List, Dict, Any
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import HTMLResponse

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
    return {"matches": ranked[:3]}

@app.post("/evaluate_counter")
async def evaluate_counter(request: Request, x_api_key: str | None = Header(None)):
    require_api_key(x_api_key)
    body = await request.json()
    load_id = body["load_id"]; carrier_offer = float(body["carrier_offer"]); round_num = int(body["round_num"])
    load = next(L for L in LOADS if L["load_id"] == load_id)
    lb = float(load["loadboard_rate"])

    max_bump = lb * 0.12  # +12% ceiling
    # +5% if pickup within 12h
    pickup = datetime.fromisoformat(load["pickup_datetime"])
    now = datetime.now(pickup.tzinfo)
    if (pickup - now).total_seconds() <= 12 * 3600: 
        max_bump += lb * 0.05

    ceiling = lb + max_bump
    if carrier_offer <= ceiling:
        decision = "accept"; broker_offer = carrier_offer
    elif round_num == 1:
        decision = "counter"; broker_offer = lb
    elif round_num == 2:
        decision = "counter"; broker_offer = min(ceiling, lb * 1.05)
    elif round_num == 3:
        decision = "counter"; broker_offer = min(ceiling, lb * 1.08)
    else:
        decision = "reject"; broker_offer = lb

    return {"decision": decision, "broker_offer": round(broker_offer, 2), "ceiling": round(ceiling, 2)}

@app.post("/log_call")
async def log_call(request: Request, x_api_key: str | None = Header(None)):
    require_api_key(x_api_key)
    body = await request.json()
    ext = body.get("extracted", {})
    con = db()
    con.execute("""
        INSERT INTO calls (call_id, timestamp, outcome, sentiment, rounds, mc, dot, legal_name,
                           selected_load_id, origin, destination, pickup_datetime, delivery_datetime,
                           equipment_type, miles, loadboard_rate, agreed_rate, transcript)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        body.get("call_id"),
        body.get("timestamp"),
        body.get("outcome"),
        body.get("sentiment"),
        ext.get("rounds"),
        ext.get("mc"),
        ext.get("dot"),
        ext.get("legal_name"),
        ext.get("selected_load_id"),
        ext.get("origin"),
        ext.get("destination"),
        ext.get("pickup_datetime"),
        ext.get("delivery_datetime"),
        ext.get("equipment_type"),
        ext.get("miles"),
        ext.get("loadboard_rate"),
        ext.get("agreed_rate"),
        body.get("transcript")
    ))
    con.commit(); con.close()
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
