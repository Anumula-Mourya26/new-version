# 🌾 AnnSetu — "Bridge to the Grain"
### *Live Gate & Queue Transparency Layer for MSP Procurement*
**Smart India Hackathon 2026 · Problem Statement 26032**  
*Ministry of Consumer Affairs, Food & Public Distribution · Theme: Smart Automation*

---

> **From "your slot is Tuesday" to "your money is in your account" — live, honest, farmer-facing MSP procurement.**

AnnSetu is a live operations layer that sits beside existing state procurement portals (MP e-Uparjan, Punjab e-Kharid/e-PMB, RAJFED, etc.) rather than replacing them. It solves the three compounding failure modes documented in field research:
1. **Live, Gate-Fed Queue Position & ETA**: Powered by deterministic M/M/c queueing theory rather than cosmetic counters or unexplainable black-box ML.
2. **Staged Payment-Trust Timeline**: The only system that explicitly models and exposes the 4-stage payment journey (Sold → Advice Generated on PFMS → Advice Reached Commission Agent/Arhatiya → Credited to Farmer DBT Account).
3. **District Congestion Command Center**: Turns passive capacity charts into an actionable 1-click redirect mechanism to balance incoming tractor traffic before mandis bottleneck.

---

## 🏛️ Comprehensive Architecture & Specification
- **[Engineering Blueprint (66 Pages)](AnnSetu_Engineering_Blueprint.docx)**: Complete 20-section specification covering data schemas, queueing engine, API contracts, notification matrices, security audit trails, and government adoption roadmap.
- **[Strategic Analysis & Jury Evaluation (13 Pages)](SIH26032_Strategic_Analysis.docx)**: Competitive analysis of 10 candidate concepts, competitor attack mitigations, and jury positioning strategy.

---

## 🚀 Quickstart & Development

### 1. Backend Setup & Local Database
AnnSetu uses **FastAPI** with async SQLAlchemy, pre-configured with a lightweight zero-dependency SQLite async engine for immediate local execution (and production-ready for PostgreSQL):

`ash
cd annsetu/backend
pip install -r requirements.txt
`

### 2. Seed Realistic Mandi Data
Populate the database with Punjab & MP mandi centres (Khanna Grain Mandi, Samrala Mandi, Sahnewal), Paddy MSP rates (₹2,320/quintal), operational slots, and active queue tokens:

`ash
python seed.py
`

### 3. Run Automated Tests
`ash
python -m pytest -v
`
All 5 test suites pass out of the box:
- 	est_health_check: Verifies API uptime and metadata
- 	est_queue_engine_mmc_math: Validates M/M/c closed-form queueing calculation across single and multi-server weighbridges
- 	est_e2e_farmer_journey: End-to-end integration test (Centres → Slot Booking → Gate Check-in → Live Queue → Weighbridge Procurement)
- 	est_staged_payment_trust_timeline: Verifies 4-stage forward progression, dispute prevention, and automatic DBT UTR generation
- 	est_district_1click_redirect: Tests dynamic multi-centre traffic diversion

### 4. Launch Backend Server
`ash
uvicorn app.main:app --reload --port 8000
`
Interactive OpenAPI documentation will be live at: http://localhost:8000/docs

---

## 📐 Deterministic M/M/c Queueing Model

AnnSetu avoids black-box neural networks for wait-time estimation. Instead, it relies on verifiable operations-research queueing formulas:

\text{ETA}(p) \approx \left\lceil \frac{p - 1}{c \times \mu} \right\rceil

Where:
- $ = Farmer's live position in queue
- $ = Number of operational weighbridges / inspection counters
- $\mu$ = Rolling service throughput (farmers/min)

Whenever an operator completes a weighing or an incoming tractor scans their QR pass at the gate, all downstream waiting farmers receive real-time sub-second ETA updates via WebSocket channels.

---

## 🛡️ Staged Payment-Trust Timeline

`
[ 1. Sold ] ──▶ [ 2. Advice Generated ] ──▶ [ 3. Advice Reached Agent ] ──▶ [ 4. Credited (DBT) ]
  Weighbridge         FCI / Markfed rail           Arhatiya / Mandi ledger         Farmer Bank Account
  Inspection          Payment Advice               Reconciliation                  UTR Generated
`

This closes the critical trust gap in mandi states where payments pass through commission agents, giving farmers full visibility into every intermediate leg of their payout.

---

## 📜 License
MIT License. Built for the Smart India Hackathon (SIH 2026).
