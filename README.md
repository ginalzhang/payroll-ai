# PayGuard AI

AI compensation audit agent. Loads an employee CSV, flags four classes of pay anomalies (underpayment, promotion without raise, salary compression, above band), and answers follow-up questions with a tool-using OpenAI chat agent.

Dataset: IBM HR Analytics Employee Attrition (1,470 employees, 9 job roles × 5 levels).

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # add your OPENAI_API_KEY (optional — dashboard works without it)
streamlit run app.py
```

Click **Load sample dataset**, or upload your own CSV export.

## Detection rules

Cohort = JobRole + JobLevel + Department. Cohorts with fewer than 5 people are not evaluated. Salary = MonthlyIncome × 12. Thresholds live in `audit_rules.Thresholds`.

| Rule | Condition | Severity |
|---|---|---|
| Underpayment | salary < 0.82 × cohort median | High |
| Underpayment | salary < 0.88 × cohort median | Medium |
| Promotion without raise | promoted within 12 months, raise < 4%, level ≥ 2 | High |
| Salary compression | tenure ≥ 10 years and 0.88 ≤ salary / median < 0.97 | Medium |
| Above band | salary > 1.28 × cohort median | Low (not in exposure) |

Exposure counts underpayment, compression and promotion shortfall only. Above-band pay is reported separately.
Rows with a missing or zero salary, blank/non-numeric required values, or a duplicate EmployeeNumber are skipped and counted.

## Features

- **Dashboard**: exposure and KPI cards, data-quality line, flags by rule (click a bar to filter), department table, and one row per flagged employee with severity/rule filters, sorting and Open/Reviewed status
- **Employee profile**: opens from any row; warning notes, cohort band, flag cards with reasons, Mark reviewed and Copy summary
- **Employees**: search by name, exact ID, role or department, with department and Flagged-only filters
- **Ask PayGuard**: answers link to employee profiles. Uses GPT-4o-mini when `OPENAI_API_KEY` is set and valid; otherwise runs local demo answers on the audit results
- **Raw data**: column toggles, search over visible columns, filtered CSV download
- **Hide salaries** masks individual dollar values on screen; exports are unaffected

## File layout

```
app.py            Streamlit UI and app state (empty / loading / error / clean / loaded)
audit_rules.py    Pure-pandas audit rules and validation
theme.py          CSS and HTML helpers for the design system (fonts/colours live in .streamlit/config.toml)
ui_events.py      Clickable HTML blocks via st.components.v2 (assets in components/)
agent.py          OpenAI tool-using chat (connected mode)
demo_agent.py     Local rule-based chat (demo mode)
schema.py         Column names + synthetic employee names
data/             IBM HR Analytics dataset
tests/            pytest suite for audit_rules
```
