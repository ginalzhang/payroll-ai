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

## File layout

```
app.py         Streamlit UI (dashboard + chat)
detectors.py   Pure-pandas anomaly rules
agent.py       OpenAI tool-using chat
schema.py      Shared constants + column mapping
data/          IBM HR Analytics dataset
```
