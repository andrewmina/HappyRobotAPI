import requests, random, uuid
from datetime import datetime, timedelta, timezone

BASE_URL = "https://carrier-api-plan-ezcrgebdesefckex.canadacentral-01.azurewebsites.net"
API_KEY  = "supersecret123"

headers = {"x-api-key": API_KEY, "Content-Type": "application/json"}

# a few real-looking loads from your dataset
loads = [
    {
        "load_id": "CHI-ATL-0815-001", "origin": "Chicago, IL", "destination": "Atlanta, GA",
        "pickup_datetime": "2025-08-15T08:00:00-05:00", "delivery_datetime": "2025-08-16T12:00:00-04:00",
        "equipment_type": "Dry Van", "miles": 716, "loadboard_rate": 1800
    },
    {
        "load_id": "DAL-MEM-0815-002", "origin": "Dallas, TX", "destination": "Memphis, TN",
        "pickup_datetime": "2025-08-15T10:00:00-05:00", "delivery_datetime": "2025-08-16T06:00:00-05:00",
        "equipment_type": "Reefer", "miles": 452, "loadboard_rate": 1500
    },
    {
        "load_id": "LAX-PHX-0816-003", "origin": "Los Angeles, CA", "destination": "Phoenix, AZ",
        "pickup_datetime": "2025-08-16T07:30:00-07:00", "delivery_datetime": "2025-08-16T18:00:00-07:00",
        "equipment_type": "Flatbed", "miles": 372, "loadboard_rate": 1200
    },
    {
        "load_id": "SEA-PDX-0816-004", "origin": "Seattle, WA", "destination": "Portland, OR",
        "pickup_datetime": "2025-08-16T06:00:00-07:00", "delivery_datetime": "2025-08-16T12:30:00-07:00",
        "equipment_type": "Dry Van", "miles": 173, "loadboard_rate": 700
    },
    {
        "load_id": "KC-STL-0816-005", "origin": "Kansas City, MO", "destination": "St. Louis, MO",
        "pickup_datetime": "2025-08-16T08:00:00-05:00", "delivery_datetime": "2025-08-16T14:00:00-05:00",
        "equipment_type": "Dry Van", "miles": 250, "loadboard_rate": 600
    }
]

sentiments = ["positive", "neutral", "negative"]
outcomes   = ["agreed_and_transferred", "counter_declined", "no_match", "carrier_unqualified"]

def make_record(i: int):
    L = random.choice(loads)
    lb = float(L["loadboard_rate"])
    # simulate negotiation
    agreed = random.choice([True, False, False])  # ~33% wins
    delta  = random.choice([-50, 0, 25, 50, 75, 100])
    agreed_rate = lb + max(0, delta) if agreed else None
    outcome = "agreed_and_transferred" if agreed else random.choice([o for o in outcomes if o!="agreed_and_transferred"])
    sentiment = random.choice(sentiments)
    rounds = random.choice([1,2,3])
    now = datetime.now(timezone.utc) - timedelta(days=random.randint(0,3), hours=random.randint(0,18))

    body = {
        "call_id": str(uuid.uuid4()),
        "timestamp": now.isoformat(),
        "outcome": outcome,
        "sentiment": sentiment,
        "extracted": {
            "rounds": rounds,
            "mc": str(300000 + random.randint(1, 699999)),
            "dot": str(1000000 + random.randint(1, 999999)),
            "legal_name": random.choice(["Acme Transport LLC","BlueLine Freight Inc","RoadStar Logistics"]),
            "selected_load_id": L["load_id"],
            "origin": L["origin"],
            "destination": L["destination"],
            "pickup_datetime": L["pickup_datetime"],
            "delivery_datetime": L["delivery_datetime"],
            "equipment_type": L["equipment_type"],
            "miles": L["miles"],
            "loadboard_rate": lb,
            "agreed_rate": agreed_rate
        },
        "transcript": f"Carrier offered {lb-50} then agreed at {agreed_rate}." if agreed else "Could not agree on rate."
    }
    return body

def seed(n=12):
    ok, fail = 0, 0
    for i in range(n):
        body = make_record(i)
        r = requests.post(f"{BASE_URL}/log_call", json=body, headers=headers, timeout=10)
        if r.ok:
            ok += 1
        else:
            fail += 1
            print(f"[{i}] FAIL {r.status_code}: {r.text}")
    print(f"Done. Inserted={ok}, Failed={fail}")

if __name__ == "__main__":
    seed(15)
    # quick check
    m = requests.get(f"{BASE_URL}/metrics.json").json()
    print("Metrics snapshot:", m)
