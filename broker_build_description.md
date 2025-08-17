# Broker-facing Build Description (Acme Logistics)

## A. Overview
Acme Logistics’ inbound carrier sales process is automated using the HappyRobot platform and a secure API. When carriers call in (via a **web call trigger**, no phone purchase required), the assistant verifies eligibility (FMCSA), finds suitable loads, negotiates rates (up to three rounds), and—if agreed—transfers the call to a rep while logging structured outcomes and sentiment for analytics.

**Goals achieved**
- Faster booking decisions, consistent pricing guardrails.
- Better carrier experience with “return-trip” convenience (backhaul finder, ≤10hr pickup).
- Full transparency via a lightweight, live metrics dashboard.

## B. End-to-End Call Flow
1. **Greeting & Identity**
   - Collect **MC/DOT** → call **FMCSA** API to verify Active/Not Out of Service.
2. **Intent & Constraints**
   - Gather lane (origin, destination), pickup window, equipment type.
3. **Load Search & Pitch**
   - `POST /search_loads` with the search criteria → return top matches → pitch the best option.
4. **Negotiation** (≤3 rounds)
   - Ask for carrier’s offer; call `POST /evaluate_counter` with `load_id`, `carrier_offer`, `round_num`.
   - Logic enforces ceiling (listed rate + 12%, +5% if urgent pickup <12h).
5. **Decision**
   - **Accept** → transfer to rep (configurable).
   - **Counter** → continue rounds.
   - **Reject** → classify & log.
6. **Backhaul Finder** (optional)
   - After selection, search for a **return load**: destination → original origin, pickup within **≤10 hours** of delivery, same equipment where possible.
7. **Post-Call Logging & Analytics**
   - `POST /log_call` with outcome, sentiment, extracted fields (MC, load_id, rates, timestamps, transcript).
   - Dashboard & `GET /metrics.json` power live reporting.

## C. Data Model (loads)
Each load includes:
- `load_id`, `origin`, `destination`, `pickup_datetime`, `delivery_datetime`
- `equipment_type`, `loadboard_rate`, `notes`
- `weight`, `commodity_type`, `num_of_pieces`, `miles`, `dimensions`

> Loads are stored in a JSON/DB for the POC and can be replaced by a live TMS or load board integration.

## D. Key APIs (backing the agent)
**Base URL:** `https://<your-app>.azurewebsites.net`  
**Auth:** all write/search endpoints require header `x-api-key: <provided separately>`

- **Health** — `GET /health` → `{ "ok": true }`
- **Search Loads** — `POST /search_loads`
- **Evaluate Counter** — `POST /evaluate_counter`
- **Backhaul support** — reuse `/search_loads` with flipped lane and pickup ≤10h
- **Log Call** — `POST /log_call`
- **Metrics** — `GET /metrics.json`, `GET /dashboard`

## E. Negotiation Logic (guardrails)
- Ceiling = `loadboard_rate + 12%` (+5% if pickup <12h)
- Round 1: Counter with listed rate if offer > ceiling; accept if ≤ ceiling.
- Round 2: Counter with min(ceiling, listed × 1.05).
- Round 3: Counter with min(ceiling, listed × 1.08).
- Else: Reject.

## F. Security
- HTTPS end-to-end (Azure-managed TLS).  
- API key required on all write/search endpoints.  
- Minimal surface area; validated inputs; errors return **400/401**.

## G. Deployment & Operations
- Containerized (Docker).  
- Cloud runtime: Azure App Service for Containers.  
- CI/CD: GitHub Actions build → ACR → deploy.  
- Config via App settings.  
- Observability: logs + `/metrics.json`.

## H. HappyRobot Wiring (high level)
- **Trigger**: Web Call Trigger.  
- **Tools**: FMCSA check, `search_loads`, `evaluate_counter`, backhaul, `log_call`.  
- **Variables**: MC/DOT, lane, equipment, offer, rounds, rate, sentiment, outcome.

## I. Assumptions & Limits (POC)
- Controlled loads dataset.  
- FMCSA dependency.  
- Rules-based negotiation; ML upgrade possible.

## J. Roadmap
- Live TMS/load board integration.  
- Dynamic pricing models.  
- CRM/TMS handoff.  
- SLA monitoring and alerting.
