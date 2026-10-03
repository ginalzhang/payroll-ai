"""PayGuard AI — local demo chat (no LLM, no API key).

Keyword-routed deterministic responder. Public entry: `demo_respond`
mirrors `agent.respond` so app.py can swap them.
"""

from __future__ import annotations

import re
import pandas as pd

from schema import (
    COL_ANNUAL_SALARY, COL_DEPT, COL_ID, COL_LEVEL, COL_NAME,
    COL_PERCENT_HIKE, COL_ROLE, COL_TENURE, COL_YEARS_SINCE_PROMO,
    RULE_COMPRESSION, RULE_MISMATCH, RULE_OVERPAY, RULE_UNDERPAY,
    SEVERITY_RANK,
)


def _money(x) -> str:
    try:
        return f"**${int(x):,}**"
    except Exception:
        return "**$?**"


def _ev(row, key, default=None):
    ev = row["evidence"] if "evidence" in row else None
    return ev.get(key, default) if isinstance(ev, dict) else default


def _filter_rule(fdf: pd.DataFrame, rule: str) -> pd.DataFrame:
    if fdf is None or fdf.empty or "rule" not in fdf.columns:
        return pd.DataFrame()
    return fdf[fdf["rule"] == rule].copy()


def _finish(msg: str, hist: list[dict], reply: str) -> tuple[str, list[dict]]:
    return reply, list(hist or []) + [
        {"role": "user", "content": msg},
        {"role": "assistant", "content": reply},
    ]


def _mismatch(fdf: pd.DataFrame) -> str:
    f = _filter_rule(fdf, RULE_MISMATCH)
    if f.empty:
        return "No promotion/raise mismatches found.\n\n💡 Want me to show overall stats instead?"
    f["_hike"] = f["evidence"].map(lambda e: e.get("percent_hike", 99) if isinstance(e, dict) else 99)
    f["_yrs"] = f["evidence"].map(lambda e: e.get("years_since_promotion", 0) if isinstance(e, dict) else 0)
    f = f.sort_values(["_hike", "_yrs"], ascending=[True, False]).head(5)
    lines = ["**Top mismatches — promoted but low raise:**", ""]
    for _, r in f.iterrows():
        lines.append(
            f"- {r['name']} (ID {int(r['employee_id'])}) — {r['role']} L{int(r['level'])} "
            f"— promoted {int(r['_yrs'])}y ago, hike {int(r['_hike'])}%"
        )
    lines.append("\nAll flagged for HR review.")
    lines.append("\n💡 Want me to see which departments have the most mismatches?")
    return "\n".join(lines)


def _top_delta(fdf: pd.DataFrame, rule: str, direction: str, n: int = 3) -> pd.DataFrame:
    """direction='under' => median-salary; 'over' => salary-median."""
    f = _filter_rule(fdf, rule)
    if f.empty:
        return f
    f["_median"] = f["evidence"].map(lambda e: e.get("cohort_median", 0) if isinstance(e, dict) else 0)
    f["_delta"] = (f["_median"] - f["annual_salary"]) if direction == "under" else (f["annual_salary"] - f["_median"])
    return f.sort_values("_delta", ascending=False).head(n)


def _pay_flag(fdf: pd.DataFrame, rule: str, direction: str) -> str:
    f = _top_delta(fdf, rule, direction)
    kind = "underpaid employees" if direction == "under" else "overpayment flags"
    verb = "gap" if direction == "under" else "over by"
    if f.empty:
        return f"No {rule} flags.\n\n💡 Want me to show the overall summary?"
    lines = [f"**Top 3 most {kind}:**", ""] if direction == "under" else [f"**Top 3 {kind}:**", ""]
    for _, r in f.iterrows():
        lines.append(
            f"- {r['name']} (ID {int(r['employee_id'])}) — {r['role']} L{int(r['level'])} "
            f"— salary {_money(r['annual_salary'])} vs cohort median {_money(r['_median'])} "
            f"({verb} {_money(r['_delta'])})"
        )
    lines.append("\nAll flagged for HR review.")
    lines.append("\n💡 Want me to check if these cluster in a specific role?")
    return "\n".join(lines)


def _compression(fdf: pd.DataFrame) -> str:
    f = _filter_rule(fdf, RULE_COMPRESSION)
    if f.empty:
        return "No salary compression flags.\n\n💡 Want me to show the overall summary?"
    f["_delta"] = f["evidence"].map(lambda e: e.get("salary_delta", 0) if isinstance(e, dict) else 0)
    f["_below"] = f["evidence"].map(lambda e: e.get("n_peers_below", 0) if isinstance(e, dict) else 0)
    f["_n"] = f["evidence"].map(lambda e: e.get("n_tenured_peers", 0) if isinstance(e, dict) else 0)
    f = f.sort_values("_delta", ascending=False).head(3)
    lines = ["**Top 3 salary compression flags:**", ""]
    for _, r in f.iterrows():
        lines.append(
            f"- {r['name']} (ID {int(r['employee_id'])}) — {r['role']} L{int(r['level'])} "
            f"— new hire at {_money(r['annual_salary'])} out-earns {int(r['_below'])}/"
            f"{int(r['_n'])} tenured peers (over median by {_money(r['_delta'])})"
        )
    lines.append("\nAll flagged for HR review.")
    lines.append("\n💡 Want me to check which role has the worst compression?")
    return "\n".join(lines)


def _group_by(fdf: pd.DataFrame, col: str, label: str, followup: str) -> str:
    if fdf is None or fdf.empty or col not in fdf.columns:
        return f"No flagged employees to group by {label}.\n\n💡 Want me to show the overall summary?"
    f = fdf.copy()
    f["_delta"] = f.apply(
        lambda r: abs(int(r["annual_salary"]) - int(_ev(r, "cohort_median", r["annual_salary"]))),
        axis=1,
    )
    grp = f.groupby(col).agg(flags=("employee_id", "count"), exposure=("_delta", "sum"))
    grp = grp.sort_values("flags", ascending=False)
    lines = [f"**Flags by {label}:**", ""]
    for k, row in grp.iterrows():
        lines.append(f"- **{k}** — {int(row['flags'])} flags, exposure ~${int(row['exposure']):,}")
    lines.append(f"\n💡 {followup}")
    return "\n".join(lines)


def _employee(message: str, df: pd.DataFrame, fdf: pd.DataFrame) -> str | None:
    m = re.search(r"(?:#|\bemployee\s+|\bid\s+)(\d{1,5})", message, flags=re.I)
    if not m:
        m = re.search(r"\b(\d{1,5})\b", message)
    if not m:
        return None
    emp_id = int(m.group(1))
    hit = df[df[COL_ID] == emp_id]
    if hit.empty:
        return (
            f"No employee found with ID {emp_id}. IDs run from 1 to about 2068.\n\n"
            "💡 Try asking for a summary of the dataset instead?"
        )
    r = hit.iloc[0]
    lines = [
        f"**{r[COL_NAME]}** (ID {emp_id})", "",
        f"- Role: {r[COL_ROLE]} L{int(r[COL_LEVEL])}",
        f"- Department: {r[COL_DEPT]}",
        f"- Salary: {_money(r[COL_ANNUAL_SALARY])}",
        f"- Tenure: {int(r[COL_TENURE])}y · last promo {int(r[COL_YEARS_SINCE_PROMO])}y ago · "
        f"last hike {int(r[COL_PERCENT_HIKE])}%",
    ]
    if fdf is not None and not fdf.empty:
        emp_flags = fdf[fdf["employee_id"] == emp_id]
        if not emp_flags.empty:
            lines.append("\n**Flags for this employee:**")
            for _, fr in emp_flags.iterrows():
                lines.append(f"- {fr['rule']} ({fr['severity']}) — {fr['reason']}")
        else:
            lines.append("\nNo flags for this employee.")
    lines.append("\n💡 Want me to compare them to the cohort median?")
    return "\n".join(lines)


def _summary(df: pd.DataFrame, fdf: pd.DataFrame, stats: pd.DataFrame) -> str:
    uniq = int(fdf["employee_id"].nunique()) if not fdf.empty else 0
    by_rule = {RULE_UNDERPAY: 0, RULE_OVERPAY: 0, RULE_COMPRESSION: 0, RULE_MISMATCH: 0}
    if not fdf.empty:
        for k, v in fdf.groupby("rule").size().to_dict().items():
            by_rule[str(k)] = int(v)
    try:
        from detectors import total_exposure
        exposure = int(total_exposure(fdf, stats)) if not fdf.empty else 0
    except Exception:
        exposure = 0
    return "\n".join([
        "**PayGuard audit summary:**", "",
        f"- Total employees: **{len(df):,}**",
        f"- Flagged employees: **{uniq:,}**",
        f"- Underpayment: {by_rule[RULE_UNDERPAY]} · Overpayment: {by_rule[RULE_OVERPAY]} "
        f"· Compression: {by_rule[RULE_COMPRESSION]} · Mismatch: {by_rule[RULE_MISMATCH]}",
        f"- Estimated exposure: **${exposure:,}**",
        "\n💡 Want me to drill into the biggest single anomaly?",
    ])


def _biggest(fdf: pd.DataFrame) -> str:
    if fdf is None or fdf.empty:
        return "No flags to rank.\n\n💡 Want me to show the overall summary?"
    f = fdf.copy()
    f["_rank"] = f["severity"].map(SEVERITY_RANK).fillna(0).astype(int)
    f["_delta"] = f.apply(
        lambda r: abs(int(r["annual_salary"]) - int(_ev(r, "cohort_median", r["annual_salary"]))),
        axis=1,
    )
    r = f.sort_values(["_rank", "_delta"], ascending=[False, False]).iloc[0]
    median = _ev(r, "cohort_median", None)
    cohort_bit = f" vs cohort median {_money(median)}" if median else ""
    dept = r.get(COL_DEPT, "unknown dept") if hasattr(r, "get") else "unknown dept"
    return (
        f"The single biggest anomaly is **{r['name']}** (ID {int(r['employee_id'])}), "
        f"a {r['role']} L{int(r['level'])} in {dept}, flagged for **{r['rule']}** at "
        f"**{r['severity']}** severity. Current salary: {_money(r['annual_salary'])}"
        f"{cohort_bit}. Reason: {r['reason']} Flagged for HR review."
        "\n\n💡 Want me to see other flags in the same department?"
    )


def _fallback() -> str:
    return (
        "I didn't catch that. Try asking about underpayment, overpayment, compression, "
        "promotions without a raise, or a specific employee ID.\n\n"
        "**Try one of these:**\n"
        "- Show me employees promoted without a raise\n"
        "- Who are the top 3 most underpaid employees?\n"
        "- Is there salary compression in any department?\n\n"
        "💡 Or ask: how many employees are flagged in total?"
    )


def demo_respond(message: str, history: list[dict], df: pd.DataFrame,
                 flagged_df: pd.DataFrame, stats: pd.DataFrame) -> tuple[str, list[dict]]:
    m = (message or "").strip().lower()
    if not m:
        return _finish(message, history, _fallback())

    if "promoted without a raise" in m or "promotion without raise" in m or "mismatch" in m:
        return _finish(message, history, _mismatch(flagged_df))
    if "underpaid" in m or "underpayment" in m:
        return _finish(message, history, _pay_flag(flagged_df, RULE_UNDERPAY, "under"))
    if "overpaid" in m or "overpayment" in m:
        return _finish(message, history, _pay_flag(flagged_df, RULE_OVERPAY, "over"))
    if "compression" in m:
        return _finish(message, history, _compression(flagged_df))
    if "which role" in m or "by role" in m:
        return _finish(message, history, _group_by(flagged_df, "role", "role",
                                                   "Want me to check which department has the most flags?"))
    if "which department" in m or "department" in m or "most flags" in m or "by department" in m:
        return _finish(message, history, _group_by(flagged_df, COL_DEPT, "department",
                                                   "Want me to drill into the biggest single anomaly?"))
    if "show employee" in m or "who is" in m or re.search(r"#\d+", m) or re.search(r"\bemployee\s+\d+", m):
        reply = _employee(message, df, flagged_df)
        if reply is not None:
            return _finish(message, history, reply)
    if "biggest" in m or "worst" in m or "largest anomaly" in m or "top flag" in m:
        return _finish(message, history, _biggest(flagged_df))
    if "how many" in m or "total" in m or "stats" in m or "summary" in m or "overview" in m:
        return _finish(message, history, _summary(df, flagged_df, stats))

    return _finish(message, history, _fallback())
