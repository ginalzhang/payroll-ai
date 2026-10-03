"""PayGuard AI chat agent (Stream D).

Tool-using OpenAI chat agent over the payroll DataFrames produced by
detectors.py. Public entry points: chat_enabled(), respond(...).
"""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from schema import (
    COL_ANNUAL_SALARY, COL_DEPT, COL_ID, COL_LEVEL, COL_NAME,
    COL_PERCENT_HIKE, COL_ROLE, COL_TENURE, COL_YEARS_SINCE_PROMO,
    RULE_COMPRESSION, RULE_MISMATCH, RULE_OVERPAY, RULE_UNDERPAY, SEVERITY_RANK,
)

MODEL = "gpt-4o-mini"
TEMPERATURE = 0.2
MAX_TOKENS = 500
MAX_TURNS = 10  # user+assistant pairs retained

SYSTEM_PROMPT = """You are PayGuard, an AI compensation audit assistant. You have access to real employee data from a company (IBM HR Analytics dataset, 1,470 employees).

RULES:
- Answer ONLY from data you can see via your tools. Never invent salary numbers, employee names, or statistics.
- When a user asks about a specific employee, call get_employee first.
- When a user asks "show me X", call list_flags with the right filter.
- When explaining a flag, cite the specific comparison (cohort median, peer salary, hike %) from the evidence.
- After answering a question, PROACTIVELY suggest ONE follow-up question the user might find interesting - but keep it to one sentence.
- Keep answers under 4 sentences unless the user asks for detail.
- Never recommend specific salary adjustments. Recommend "HR review" or "deeper investigation."
- The 4 rules are: underpayment, overpayment, compression, mismatch (promoted recently but low hike).
- You may NOT infer attributes like gender bias, discrimination patterns, or legal violations without the user asking explicitly and even then present as hypothesis for HR to investigate.
"""


# ---------- Public API ----------

def chat_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


# ---------- Tool schemas ----------

def _schema(name, desc, props, required):
    return {
        "type": "function",
        "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


TOOL_SCHEMAS = [
    _schema(
        "get_employee", "Fetch a single employee's compensation record by EmployeeNumber.",
        {"employee_id": {"type": "integer", "description": "EmployeeNumber"}},
        ["employee_id"],
    ),
    _schema(
        "list_flags", "List flagged employees, optionally filtered by rule or severity.",
        {
            "rule": {"type": "string", "enum": [RULE_UNDERPAY, RULE_OVERPAY, RULE_COMPRESSION, RULE_MISMATCH]},
            "severity": {"type": "string", "enum": ["High", "Medium", "Low"]},
            "limit": {"type": "integer", "default": 10},
        },
        [],
    ),
    _schema(
        "cohort_stats_tool", "Return cohort salary stats (size, median, Q1, Q3, fences) for a role+level.",
        {"role": {"type": "string"}, "level": {"type": "integer"}},
        ["role", "level"],
    ),
    _schema(
        "compare_employees", "Side-by-side comparison of two employees with salary, tenure, promo deltas.",
        {"id_a": {"type": "integer"}, "id_b": {"type": "integer"}},
        ["id_a", "id_b"],
    ),
]


# ---------- Tool implementations ----------

def _emp_row(df: pd.DataFrame, employee_id: int) -> dict | None:
    hit = df[df[COL_ID] == int(employee_id)]
    if hit.empty:
        return None
    r = hit.iloc[0]
    return {
        "id": int(r[COL_ID]), "name": str(r[COL_NAME]), "role": str(r[COL_ROLE]),
        "level": int(r[COL_LEVEL]), "department": str(r[COL_DEPT]),
        "annual_salary": int(r[COL_ANNUAL_SALARY]), "tenure_years": int(r[COL_TENURE]),
        "years_since_promotion": int(r[COL_YEARS_SINCE_PROMO]),
        "percent_hike": int(r[COL_PERCENT_HIKE]),
    }


def _tool_get_employee(df, flagged_df, stats, employee_id: int) -> dict:
    row = _emp_row(df, int(employee_id))
    if row is None:
        return {"error": f"No employee found with id {employee_id}"}
    return row


def _tool_list_flags(df, flagged_df, stats, rule=None, severity=None, limit=10) -> list:
    if flagged_df is None or flagged_df.empty:
        return []
    f = flagged_df.copy()
    if rule:
        f = f[f["rule"] == rule]
    if severity:
        f = f[f["severity"] == severity]
    if f.empty:
        return []
    # severity rank, then salary delta from cohort median desc
    if "severity_rank" not in f.columns:
        f["severity_rank"] = f["severity"].map(SEVERITY_RANK).fillna(0).astype(int)

    def _delta(row):
        ev = row.get("evidence") or {}
        if isinstance(ev, dict) and "cohort_median" in ev:
            return abs(int(row["annual_salary"]) - int(ev["cohort_median"]))
        return 0

    f["_delta"] = f.apply(_delta, axis=1)
    f = f.sort_values(["severity_rank", "_delta"], ascending=[False, False])
    limit = max(1, min(int(limit or 10), 50))
    return [
        {"id": int(r["employee_id"]), "name": str(r["name"]), "role": str(r["role"]),
         "level": int(r["level"]), "salary": int(r["annual_salary"]),
         "rule": str(r["rule"]), "severity": str(r["severity"]),
         "reason": str(r["reason"])}
        for _, r in f.head(limit).iterrows()
    ]


def _tool_cohort_stats(df, flagged_df, stats, role: str, level: int) -> dict:
    key = f"{role} L{int(level)}"
    if stats is None or key not in stats.index:
        return {"error": f"No qualifying cohort for '{role}' L{level} (need >= 4 employees)."}
    s = stats.loc[key]
    return {"cohort": key, "size": int(s["size"]),
            "median": int(round(float(s["median"]))), "Q1": int(round(float(s["Q1"]))),
            "Q3": int(round(float(s["Q3"]))),
            "lower_fence": int(round(float(s["lower_fence"]))),
            "upper_fence": int(round(float(s["upper_fence"])))}


def _tool_compare_employees(df, flagged_df, stats, id_a: int, id_b: int) -> dict:
    a = _emp_row(df, int(id_a))
    b = _emp_row(df, int(id_b))
    if a is None or b is None:
        return {"error": f"Missing employee(s): a={a is not None}, b={b is not None}"}
    return {"a": a, "b": b, "delta": {
        "salary": a["annual_salary"] - b["annual_salary"],
        "tenure_years": a["tenure_years"] - b["tenure_years"],
        "years_since_promotion": a["years_since_promotion"] - b["years_since_promotion"],
    }}


TOOL_IMPLS = {
    "get_employee": _tool_get_employee,
    "list_flags": _tool_list_flags,
    "cohort_stats_tool": _tool_cohort_stats,
    "compare_employees": _tool_compare_employees,
}


# ---------- Fact sheet ----------

def _fact_sheet(df: pd.DataFrame, flagged_df: pd.DataFrame, stats: pd.DataFrame) -> str:
    try:
        from detectors import total_exposure
        exposure = int(total_exposure(flagged_df, stats)) if not flagged_df.empty else 0
    except Exception:
        exposure = 0
    uniq = int(flagged_df["employee_id"].nunique()) if not flagged_df.empty else 0
    by_rule = {RULE_UNDERPAY: 0, RULE_OVERPAY: 0, RULE_COMPRESSION: 0, RULE_MISMATCH: 0}
    if not flagged_df.empty:
        for k, v in flagged_df.groupby("rule").size().to_dict().items():
            by_rule[str(k)] = int(v)
    top_lines = ["  - (none)"]
    if not flagged_df.empty:
        f = flagged_df.copy()
        f["sev_rank"] = f["severity"].map(SEVERITY_RANK).fillna(0).astype(int)
        f = f.sort_values(["sev_rank", "annual_salary"], ascending=[False, False])
        top_lines = [
            f"  - id={int(r['employee_id'])} {r['name']} ({r['rule']}) ${int(r['annual_salary']):,}"
            for _, r in f.head(5).iterrows()
        ]
    return "\n".join([
        "# PAYGUARD FACTS (current session)",
        f"- Total employees: {len(df):,}",
        f"- Flagged employees: {uniq:,}",
        f"- Flags by rule: underpayment={by_rule[RULE_UNDERPAY]}, overpayment={by_rule[RULE_OVERPAY]}, compression={by_rule[RULE_COMPRESSION]}, mismatch={by_rule[RULE_MISMATCH]}",
        f"- Cohorts analyzed: {0 if stats is None else len(stats)}",
        f"- Total exposure: ${exposure:,}",
        "- Top 5 flagged by severity:",
        *top_lines,
    ])


# ---------- History management ----------

def _trim_history(history: list[dict]) -> list[dict]:
    """Keep only the last MAX_TURNS user+assistant pairs."""
    non_system = [m for m in history if m.get("role") != "system"]
    # Count user turns from the end
    kept: list[dict] = []
    user_count = 0
    for msg in reversed(non_system):
        kept.append(msg)
        if msg.get("role") == "user":
            user_count += 1
            if user_count >= MAX_TURNS:
                break
    kept.reverse()
    return kept


# ---------- Main respond ----------

def respond(message: str, history: list[dict], df: pd.DataFrame,
            flagged_df: pd.DataFrame, stats: pd.DataFrame) -> tuple[str, list[dict]]:
    try:
        from openai import OpenAI
    except Exception as e:
        return (f"⚠️ Chat unavailable: openai SDK not installed ({e}).", history)
    if not chat_enabled():
        return ("⚠️ Chat unavailable: OPENAI_API_KEY not set.", history)

    history = list(history or [])
    trimmed = _trim_history(history) + [{"role": "user", "content": message}]
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": _fact_sheet(df, flagged_df, stats)},
    ] + trimmed

    try:
        client = OpenAI()
    except Exception as e:
        return (f"⚠️ Chat unavailable: {e}. Try again or check your API key.", history)

    def _finish(text: str) -> tuple[str, list[dict]]:
        return (text, history + [{"role": "user", "content": message},
                                 {"role": "assistant", "content": text}])

    for _ in range(5):
        try:
            resp = client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOL_SCHEMAS,
                temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
            )
        except Exception as e:
            return (f"⚠️ Chat unavailable: {e}. Try again or check your API key.", history)

        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            return _finish((msg.content or "").strip())

        messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            impl = TOOL_IMPLS.get(name)
            result: Any
            if impl is None:
                result = {"error": f"Unknown tool: {name}"}
            else:
                try:
                    result = impl(df, flagged_df, stats, **args)
                except Exception as e:
                    result = {"error": f"Tool {name} failed: {e}"}
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, default=str)})

    return _finish("⚠️ The model took too many tool-call steps. Please rephrase.")
