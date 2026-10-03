"""PayGuard AI — local demo chat (no LLM, no API key).

Keyword-routed responder over the current audit run. Answers are structured so
the UI can render clickable employee rows:

    {"text": str, "rows": [{"id", "a", "b", "c", "tone"}], "foot": str}

`id` opens that employee's profile; rows with id=None are not clickable.
`tone` is "high", "medium" or "muted" and only colours the right-hand value.
"""

from __future__ import annotations

import re

import pandas as pd

from audit_rules import AuditResult
from theme import pct

FALLBACK = (
    "In demo mode I can answer questions about underpayment, promotions without raises, "
    "salary compression, or a specific employee by full name or #ID. "
    "Connect an OpenAI key for open-ended questions."
)


def _who(e: pd.Series) -> str:
    return f"#{int(e['EmployeeNumber'])} · {e['JobRole']} L{int(e['JobLevel'])}"


def _with_rule(res: AuditResult, rule: str) -> pd.DataFrame:
    if res.flags.empty:
        return res.employees.iloc[0:0]
    ids = res.flags.loc[res.flags["rule"] == rule, "EmployeeNumber"]
    return res.employees[res.employees["EmployeeNumber"].isin(ids)]


def _underpaid(res: AuditResult, foot: str) -> dict:
    top = _with_rule(res, "under").sort_values("ratio").head(3)
    if top.empty:
        return {"text": "No one is paid below 88% of their cohort median.", "rows": [], "foot": foot}
    rows = [{"id": int(e["EmployeeNumber"]), "a": e["Name"], "b": _who(e),
             "c": pct(e["ratio"]), "tone": "high"} for _, e in top.iterrows()]
    n = len(rows)
    lead = "These three are" if n == 3 else f"{'These' if n > 1 else 'This'} {n} {'are' if n > 1 else 'is'}"
    return {"text": f"{lead} furthest below their cohort median, measured as a percentage gap:",
            "rows": rows, "foot": foot}


def _promo(res: AuditResult, foot: str) -> dict:
    p = _with_rule(res, "promo").sort_values("PercentSalaryHike")
    if p.empty:
        return {"text": "No one was promoted in the last 12 months with a raise under 4%.", "rows": [], "foot": foot}
    rows = [{"id": int(e["EmployeeNumber"]), "a": e["Name"], "b": _who(e),
             "c": f"{e['PercentSalaryHike']:g}% raise", "tone": "high"} for _, e in p.head(5).iterrows()]
    more = f" · {len(p) - 5} more in Dashboard → Promo / raise" if len(p) > 5 else ""
    return {"text": f"{len(p)} employees were promoted in the last 12 months with a raise under 4%. "
                    "Lowest raises first:", "rows": rows, "foot": foot + more}


def _compression(res: AuditResult, foot: str) -> dict:
    by = _with_rule(res, "comp")["Department"].value_counts()
    if by.empty:
        return {"text": "No compression found in any department.", "rows": [], "foot": foot}
    rows = [{"id": None, "a": str(d), "b": "", "c": f"{n} employees", "tone": "medium"} for d, n in by.items()]
    return {"text": "Yes. Compression flags (10+ years tenure, paid below cohort median) by department:",
            "rows": rows, "foot": foot}


def _people(res: AuditResult, q: str, foot: str) -> dict | None:
    e = res.employees
    ids = {int(m) for m in re.findall(r"(?:#|\bemployee\s+|\bid\s+)(\d{1,6})\b", q)}
    names = e["Name"].astype(str).str.lower()
    hit = e[e["EmployeeNumber"].isin(ids) | names.map(lambda n: bool(n) and n in q)]
    if hit.empty:
        if ids:
            return {"text": f"No employee has ID {', '.join('#' + str(i) for i in sorted(ids))} in this run.",
                    "rows": [], "foot": foot}
        return None
    rows = []
    for _, r in hit.head(5).iterrows():
        n = int(r["flag_count"])
        rows.append({"id": int(r["EmployeeNumber"]), "a": r["Name"], "b": _who(r),
                     "c": f"{n} flag{'s' if n != 1 else ''}" if n else "No flags",
                     "tone": "high" if n else "muted"})
    if len(hit) > 1:
        text = f"{len(hit)} employees match. Pick one to see their profile:"
    else:
        n = int(hit.iloc[0]["flag_count"])
        text = f"{hit.iloc[0]['Name']} has {n or 'no'} flag{'' if n == 1 else 's'}."
    return {"text": text, "rows": rows, "foot": foot}


def answer(question: str, res: AuditResult, foot: str) -> dict:
    q = (question or "").strip().lower()
    if re.search(r"underpaid|underpay|lowest paid", q):
        return _underpaid(res, foot)
    if re.search(r"promot|raise", q):
        return _promo(res, foot)
    if "compress" in q:
        return _compression(res, foot)
    hit = _people(res, q, foot)
    if hit:
        return hit
    return {"text": FALLBACK, "rows": [], "foot": ""}
