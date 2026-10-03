# PayGuard AI

AI compensation audit agent. Loads an employee CSV, flags four classes of compensation anomalies (underpayment, overpayment, salary compression, promotion/raise mismatch), and answers follow-up questions with a tool-using OpenAI chat agent.

Dataset: IBM HR Analytics Employee Attrition (1,470 employees, 9 job roles × 5 levels).

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # add your OPENAI_API_KEY (optional — dashboard works without it)
streamlit run app.py
```

Open the sidebar and click **Load dataset**.

## Detection rules

Cohort = same JobRole AND JobLevel. Requires n ≥ 4 members.

- 🔴 **Underpayment** (High) — salary < cohort median − 1.5 × IQR, tenure ≥ 1 year
- 🟡 **Overpayment** (Low) — salary > cohort median + 1.5 × IQR
- 🟠 **Compression** (Medium) — new hire (≤ 1 year) earning more than a peer with ≥ 2 years tenure in the same cohort
- 🔵 **Promotion / raise mismatch** (High) — promoted within last 2 years but received < 5% hike

## Features

- **Dashboard** — hero exposure number ($4.1M on bundled data), KPI cards, flagged employee table with cohort box plot + histogram evidence
- **Employee lookup** — search by name, ID, role, or department. Full profile with career timeline (joined, promoted, raise history), flags, cohort comparison, and attributes
- **Ask PayGuard** — tool-using chat agent. Uses GPT-4o-mini when `OPENAI_API_KEY` is set; runs a local demo-mode chat on the real data when it isn't

## File layout

```
app.py         Streamlit UI (4 tabs)
detectors.py   Pure-pandas anomaly rules
agent.py       OpenAI tool-using chat (live mode)
demo_agent.py  Local rule-based chat (no-API mode)
schema.py      Shared constants + column mapping
data/          IBM HR Analytics dataset
```
