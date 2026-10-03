"""PayGuard AI chat agent (connected mode).

Tool-using OpenAI chat over the current audit run. Public entry points:
chat_enabled(), check_connection(), respond(...).

respond() returns the same answer shape as demo_agent.answer() plus an
`error` key ("auth", "timeout" or None) so the UI can switch to offline mode.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from audit_rules import RULE_NAMES, AuditResult, summary

MODEL = "gpt-4o-mini"
TEMPERATURE = 0.2
MAX_TOKENS = 500
MAX_TURNS = 10  # user+assistant pairs retained
TIMEOUT_S = 20

SYSTEM_PROMPT = """You are PayGuard, a compensation audit assistant. You answer questions about one audit run over an HR export.

RULES:
- Answer ONLY from data you can see via your tools. Never invent salary numbers, employee names, or statistics.
- Always refer to employees by name AND #EmployeeNumber, because names are not unique.
- When a user asks about a specific employee, call get_employee first.
- When explaining a flag, cite the cohort median and the gap from the tool result.
- Keep answers under 4 sentences unless the user asks for detail. Plain text, no markdown tables.
- Never recommend specific salary adjustments. Recommend "HR review" or "deeper investigation."
- Cohort = JobRole + JobLevel + Department; cohorts with fewer than 5 people are not evaluated.
- The 4 rules are: under (Underpayment), promo (Promotion without raise), comp (Salary compression), over (Above band, not counted in exposure).
- Do not infer discrimination or legal violations. If asked, present only as a hypothesis for HR to investigate.
"""


def chat_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _classify(e: Exception) -> str:
    try:
        import openai
    except Exception:
        return "error"
    if isinstance(e, openai.AuthenticationError):
        return "auth"
    if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError)):
        return "timeout"
    return "error"


def check_connection() -> str | None:
    """Cheap key check at startup. Returns None if usable, else "auth"/"timeout"/"error"."""
    try:
        from openai import OpenAI
        OpenAI(timeout=8, max_retries=0).models.retrieve(MODEL)
        return None
    except Exception as e:
        return _classify(e)


# ---------- Tools ----------

def _schema(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


TOOL_SCHEMAS = [
    _schema("get_employee", "Fetch one employee's audit record by EmployeeNumber, including flags and cohort stats.",
            {"employee_id": {"type": "integer"}}, ["employee_id"]),
    _schema("find_employees", "Find employees whose name contains the given text.",
            {"name": {"type": "string"}}, ["name"]),
    _schema("list_flags", "List flagged employees, optionally filtered by rule, severity or department, "
                          "sorted by severity then estimated adjustment.",
            {"rule": {"type": "string", "enum": list(RULE_NAMES)},
             "severity": {"type": "string", "enum": ["High", "Medium", "Low"]},
             "department": {"type": "string"},
             "limit": {"type": "integer", "default": 10}}, []),
    _schema("audit_summary", "Totals for this audit run: evaluated, flagged, exposure, flags by rule and department.",
            {}, []),
]


def _num(v):
    return None if pd.isna(v) else (int(v) if float(v).is_integer() else round(float(v), 2))


def _emp_dict(e: pd.Series, flags: pd.DataFrame) -> dict:
    eid = int(e["EmployeeNumber"])
    own = flags[flags["EmployeeNumber"] == eid] if not flags.empty else flags
    return {
        "id": eid, "name": str(e["Name"]), "role": str(e["JobRole"]), "level": _num(e["JobLevel"]),
        "department": str(e["Department"]), "annual_salary": _num(e["AnnualSalary"]),
        "evaluated": bool(e["evaluated"]), "cohort_size": _num(e["n"]), "cohort_median": _num(e["median"]),
        "gap_to_median": _num(e["gap"]), "tenure_years": _num(e["YearsAtCompany"]),
        "years_since_promotion": _num(e["YearsSinceLastPromotion"]),
        "last_raise_pct": _num(e["PercentSalaryHike"]),
        "flags": [{"rule": r["rule"], "severity": r["severity"], "reason": r["reason"],
                   "est_adjustment": _num(r["impact"])} for _, r in own.iterrows()],
    }


def _run_tool(name: str, args: dict, res: AuditResult) -> Any:
    e = res.employees
    if name == "get_employee":
        hit = e[e["EmployeeNumber"] == int(args.get("employee_id", -1))]
        return _emp_dict(hit.iloc[0], res.flags) if len(hit) else {"error": "No employee with that ID"}
    if name == "find_employees":
        q = str(args.get("name", "")).lower()
        hit = e[e["Name"].astype(str).str.lower().str.contains(q, regex=False)].head(10)
        return [{"id": int(r["EmployeeNumber"]), "name": r["Name"], "role": r["JobRole"],
                 "level": _num(r["JobLevel"]), "department": r["Department"]} for _, r in hit.iterrows()]
    if name == "list_flags":
        f = res.flags
        if f.empty:
            return []
        if args.get("rule"):
            f = f[f["rule"] == args["rule"]]
        if args.get("severity"):
            f = f[f["severity"] == args["severity"]]
        ids = f["EmployeeNumber"].unique()
        sub = e[e["EmployeeNumber"].isin(ids)]
        if args.get("department"):
            sub = sub[sub["Department"].str.lower() == str(args["department"]).lower()]
        rank = {"High": 3, "Medium": 2, "Low": 1}
        sub = sub.assign(_r=sub["top_severity"].map(rank)).sort_values(["_r", "exposure"], ascending=False)
        limit = max(1, min(int(args.get("limit") or 10), 50))
        return [_emp_dict(r, res.flags) for _, r in sub.head(limit).iterrows()]
    if name == "audit_summary":
        s = summary(res)
        by_rule = res.flags.groupby(["rule", "severity"]).size().to_dict() if not res.flags.empty else {}
        flagged = e[e["flag_count"] > 0]
        by_dept = flagged.groupby("Department").agg(flagged=("EmployeeNumber", "size"), exposure=("exposure", "sum"))
        return {**s, "flags_by_rule": {f"{r}/{sv}": int(n) for (r, sv), n in by_rule.items()},
                "by_department": {d: {"flagged": int(r["flagged"]), "exposure": round(float(r["exposure"]))}
                                  for d, r in by_dept.iterrows()},
                "note": "exposure excludes Above band"}
    return {"error": f"Unknown tool: {name}"}


def _trim_history(history: list[dict]) -> list[dict]:
    kept, users = [], 0
    for msg in reversed(history):
        kept.append(msg)
        if msg.get("role") == "user":
            users += 1
            if users >= MAX_TURNS:
                break
    return list(reversed(kept))


def _mentioned_rows(text: str, seen: dict[int, dict]) -> list[dict]:
    """Employees from tool results that the final answer actually mentions."""
    rows = []
    for eid, d in seen.items():
        if re.search(rf"#?\b{eid}\b", text) or d["name"] in text:
            n = len(d.get("flags", []))
            rows.append({"id": eid, "a": d["name"], "b": f"#{eid} · {d['role']} L{d['level']}",
                         "c": f"{n} flag{'s' if n != 1 else ''}" if n else "No flags",
                         "tone": "high" if n else "muted"})
    return rows[:8]


def respond(message: str, history: list[dict], res: AuditResult, foot: str) -> tuple[dict, list[dict]]:
    """Returns (answer, new_history). answer["error"] is set if the API call failed."""
    from openai import OpenAI

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}] + _trim_history(history) + [
        {"role": "user", "content": message}]
    seen: dict[int, dict] = {}

    try:
        client = OpenAI(timeout=TIMEOUT_S, max_retries=1)
        for _ in range(5):
            resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOL_SCHEMAS,
                                                  temperature=TEMPERATURE, max_tokens=MAX_TOKENS)
            msg = resp.choices[0].message
            if not msg.tool_calls:
                text = (msg.content or "").strip()
                new_history = history + [{"role": "user", "content": message},
                                         {"role": "assistant", "content": text}]
                return {"text": text, "rows": _mentioned_rows(text, seen), "foot": foot, "error": None}, new_history
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                try:
                    result = _run_tool(tc.function.name, args, res)
                except Exception as e:
                    result = {"error": f"Tool failed: {e}"}
                for d in result if isinstance(result, list) else [result]:
                    if isinstance(d, dict) and "id" in d and "name" in d:
                        seen.setdefault(d["id"], d)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result, default=str)})
    except Exception as e:
        kind = _classify(e)
        text = {"auth": "OpenAI rejected the API key (401).",
                "timeout": "OpenAI did not respond in time."}.get(kind, f"The request failed: {e}")
        return {"text": text, "rows": [], "foot": "", "error": kind}, history

    return {"text": "That took too many lookup steps. Try a narrower question.", "rows": [], "foot": foot,
            "error": None}, history
