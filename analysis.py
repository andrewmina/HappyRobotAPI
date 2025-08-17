from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import pypandoc

# Download pandoc if not present
pypandoc.download_pandoc()

# File paths
pdf_path = "broker_build_description.pdf"
txt_path = "email_to_client.txt"
md_path = "broker_build_description.md"

# Email content
email_content = """To: c.becker@happyrobot.ai
Cc: <your recruiter’s email>
Subject: Inbound Carrier Sales POC — latest progress, demo links & next steps

Hi Carlos,

Ahead of our meeting, here’s a quick update on the Inbound Carrier Sales proof-of-concept:

What’s working now
* Inbound voice flow in HappyRobot: MC/DOT capture → FMCSA eligibility check → load search → pitch → 3-round negotiation → accept/transfer or decline → outcome & sentiment classification → call logging.
* Backhaul finder: Optional step to identify a return load (delivery city → back to origin) within ≤ 10 hours of drop-off, same equipment preference.
* Secure API (FastAPI) backing the flow: /search_loads, /evaluate_counter, /log_call, /metrics.json, /dashboard, and utility /add-hours for time math.
* Metrics dashboard: Daily volume, wins, sentiment mix, equipment mix, avg agreed vs listed delta.
* Containerized deployment on Azure (App Service for Containers) with CI/CD via GitHub Actions (build→push to ACR→deploy).
* Security: HTTPS and API key required on all write/search endpoints.

Demo assets
* Web call trigger (browser-based “inbound call” — no phone number required): <link to your HappyRobot Web Call Trigger>
* Dashboard (live): https://<your-app>.azurewebsites.net/dashboard
* API base: https://<your-app>.azurewebsites.net

What I’ll walk through live
1. End-to-end inbound call, including MC verification and negotiation.
2. Backhaul suggestion within the 10-hour window.
3. Dashboard review and raw metrics endpoint.
4. Deployment & security posture.

Next steps / questions for you
* Any specific lanes/equipment you want me to preload for the demo?
* Preferred escalation path once a rate is accepted (transfer target, metadata to pass along)?
* Optional: add your CRM/TMS webhook for confirmed loads.

Thanks, and looking forward to the session!

Best,
<Your Name>
<Title> | <Company>
<Phone> | <Calendar link (optional)>
"""

# Save email as txt
with open("email_to_client.txt", "w", encoding="utf-8") as f:
    f.write(email_content)

# Broker build description content (Markdown for reuse)
broker_md = """# Broker-facing Build Description (Acme Logistics)

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
"""

# Save Markdown file
with open(md_path, "w", encoding="utf-8") as f:
    f.write(broker_md)

# Generate PDF from Markdown using pypandoc
pypandoc.convert_text(
    broker_md,
    'pdf',
    format='md',
    outputfile=pdf_path,
    extra_args=['--standalone', '--pdf-engine=wkhtmltopdf']  # or weasyprint
)

doc = SimpleDocTemplate(pdf_path, pagesize=LETTER)
styles = getSampleStyleSheet()
story = [Paragraph(line, styles["Normal"]) for line in broker_md.split("\n")]
doc.build(story)
