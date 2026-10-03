"""PayGuard AI — Streamlit UI.

One `st.session_state.app_state` drives what renders:
empty → loading → loaded | clean, or loading → error (previous results kept).
"""

from __future__ import annotations

import copy
import io
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

import agent
import demo_agent
import theme
from audit_rules import REQUIRED_COLUMNS, RULE_NAMES, SEV_RANK, run_audit, summary, validate
from schema import COL_NAME, DATA_PATH, synthesize_name
from theme import (AMBER, FAINT, MINT, MUTED, RULE_DESC, RULE_SHORT, SEV, SEV_ORDER, SOFT, TEXT, TONE,
                   esc, md, money, pct)
from ui_events import html_block

st.set_page_config(page_title="PayGuard AI", layout="wide")
theme.inject()
ss = st.session_state

PAGE = 25
DEFAULTS = {
    "app_state": "empty", "reviewed": {}, "masked": False,
    "f_sev": "All", "f_rule": "All", "f_sort": "impact", "f_dir": -1, "f_limit": PAGE, "chart_v": 0,
    "e_dept": "All", "e_flagged": None, "e_page": 0, "profile_id": None,
    "r_cols": None, "r_page": 0,
    "msgs": [], "llm_history": [], "chat_pending": None,
}
for _k, _v in DEFAULTS.items():
    ss.setdefault(_k, copy.deepcopy(_v))

if "ai_mode" not in ss:
    if not agent.chat_enabled():
        ss.ai_mode, ss.ai_error = "demo", None
    else:
        err = agent.check_connection()
        ss.ai_mode = "offline" if err else "connected"
        ss.ai_error = err

masked = bool(ss.masked)


# ---------- Formatting ----------

def fmt_dt(dt: datetime) -> str:
    return f"{dt.day} {dt:%b %Y}, {dt:%-I:%M %p}"


def n_(v) -> str:
    return "—" if pd.isna(v) else f"{v:g}" if isinstance(v, float) else str(v)


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


# ---------- Loading ----------

def start_audit(name: str, data: bytes):
    ss.pending = {"name": name, "bytes": data}
    ss.app_state = "loading"


def load_sample():
    start_audit("ibm_hr_attrition.csv", DATA_PATH.read_bytes())


def on_upload(key: str):
    f = ss.get(key)
    if f is None:
        return
    ss.up_n = ss.get("up_n", 0) + 1   # fresh uploader keys, so they show as empty buttons again
    if not f.name.lower().endswith(".csv"):
        set_error(f.name, [], "PayGuard reads CSV files. Export the report as .csv and try again.",
                  "not a CSV file.")
    else:
        start_audit(f.name, f.getvalue())


def set_error(name: str, checks: list[dict], message: str, short: str):
    ss.error = {"name": name, "checks": checks, "message": message, "short": short}
    ss.app_state = "error"
    ss.pop("pending", None)


def fail(name: str, checks: list[dict], message: str, short: str):
    set_error(name, checks, message, short)
    st.rerun()


def add_names(df: pd.DataFrame) -> pd.DataFrame:
    if COL_NAME not in df.columns:
        ids = pd.to_numeric(df["EmployeeNumber"], errors="coerce")
        df[COL_NAME] = [synthesize_name(int(i)) if pd.notna(i) else "Unknown" for i in ids]
    return df


def loading_panel(name: str, sub: str, step: int) -> str:
    labels = ["Reading file", "Validating columns", "Building cohorts", "Running 4 audit rules"]
    items = []
    for i, label in enumerate(labels):
        state = "done" if i < step else "active" if i == step else "pending"
        ring = "#2A2F37" if state == "pending" else MINT
        fill = MINT if state == "done" else "transparent"
        color = "#6F7682" if state == "pending" else TEXT
        icon = "✓" if state == "done" else ""
        items.append(f'<div style="display:flex;align-items:center;gap:12px;font-size:14px;color:{color}">'
                     f'<span style="width:18px;height:18px;border-radius:50%;display:grid;place-items:center;font-size:11px;'
                     f'border:1px solid {ring};background:{fill};color:#0E1013">{icon}</span><span>{label}</span></div>')
    width = (step + 0.5) / len(labels) * 100
    return (f'<div style="border:1px solid #22262D;border-radius:14px;padding:32px;display:flex;flex-direction:column;'
            f'gap:20px;max-width:560px;background:#13161B">'
            f'<div style="display:flex;flex-direction:column;gap:6px"><h1 style="font-size:20px !important">Running audit</h1>'
            f'<div style="font-size:13px;color:{MUTED}">{esc(sub)}</div></div>'
            f'<div style="height:4px;border-radius:2px;background:#22262D;overflow:hidden">'
            f'<div style="height:100%;background:{MINT};width:{width}%"></div></div>'
            f'<div style="display:flex;flex-direction:column;gap:12px">{"".join(items)}</div></div>')


def run_loading():
    p = ss.pending
    box = st.empty()
    box.html(loading_panel(p["name"], p["name"], 0))
    try:
        raw = pd.read_csv(io.BytesIO(p["bytes"]))
    except Exception as e:
        fail(p["name"], [], f"The file couldn't be read as CSV ({e}).", "not a readable CSV file.")
    sub = f"{p['name']} · {plural(len(raw), 'row')}"
    box.html(loading_panel(p["name"], sub, 1))
    v = validate(raw)
    if not v.ok:
        missing = sum(c["status"] == "missing" for c in v.checks)
        if missing:
            fail(p["name"], v.checks, f"The file loaded, but it's missing {plural(missing, 'column')} PayGuard needs.",
                 f"{plural(missing, 'required column')} missing.")
        fail(p["name"], v.checks, "The file loaded, but it has no data rows.", "the file has no data rows.")
    box.html(loading_panel(p["name"], sub, 2))
    try:
        raw = add_names(raw)
        res = run_audit(raw)
    except Exception as e:
        fail(p["name"], v.checks, f"The columns are present, but the audit failed on this file ({e}).",
             "the audit could not run on this file.")
    box.html(loading_panel(p["name"], sub, 3))
    flag_lists: dict[int, list] = {}
    for r in res.flags.sort_values("severity", key=lambda s: -s.map(SEV_RANK)).itertuples():
        flag_lists.setdefault(int(r.EmployeeNumber), []).append(r)
    ss.audit = {"res": res, "summary": summary(res), "flags": flag_lists, "name": p["name"],
                "rows": len(raw), "cols": len(raw.columns) - (1 if COL_NAME in raw.columns else 0),
                "raw": raw, "at": datetime.now()}
    ss.source = {"name": p["name"], "bytes": p["bytes"]}
    ss.app_state = "loaded" if len(res.flags) else "clean"
    ss.pop("pending", None)
    ss.pop("error", None)
    ss.f_limit, ss.e_page, ss.r_page, ss.profile_id = PAGE, 0, 0, None
    st.rerun()


# ---------- Shared bits ----------

def flags_of(eid: int) -> list:
    return ss.audit["flags"].get(eid, [])


def is_reviewed(eid: int) -> bool:
    return bool(ss.reviewed.get(eid))


def footnote() -> str:
    a = ss.audit
    return f"Based on {a['summary']['evaluated']:,} evaluated rows · run {a['at'].day} {a['at']:%b %Y}"


def flagged_csv() -> bytes:
    res = ss.audit["res"]
    e = res.employees[res.employees["flag_count"] > 0]
    out = pd.DataFrame({
        "EmployeeNumber": e["EmployeeNumber"], "Name": e[COL_NAME], "JobRole": e["JobRole"],
        "JobLevel": e["JobLevel"], "Department": e["Department"], "AnnualSalary": e["AnnualSalary"].round(),
        "CohortMedian": e["median"].round(), "Severity": e["top_severity"],
        "Rules": [", ".join(RULE_NAMES[f.rule] for f in flags_of(i)) for i in e["EmployeeNumber"]],
        "EstAdjustment": e["exposure"].round(),
        "Status": ["Reviewed" if is_reviewed(i) else "Open" for i in e["EmployeeNumber"]],
    })
    return out.to_csv(index=False).encode()


def chips(key: str, options: dict, multi: bool = False, **on_change):
    """Filter chips. `options` maps value -> label; `on_change` values are applied to session state."""
    st.pills(key, list(options), key=key, format_func=options.get, label_visibility="collapsed",
             selection_mode="multi" if multi else "single", required=not multi and key != "e_flagged",
             on_change=set_state, kwargs=on_change)


def set_state(**kw):
    for k, v in kw.items():
        ss[k] = v


def open_profile(eid):
    ss.profile_id = int(eid)


def close_profile():
    ss.profile_id = None


# ---------- Sidebar ----------

def sidebar():
    state = ss.app_state
    md(f'<div style="display:flex;flex-direction:column;gap:6px"><div style="display:flex;align-items:center;gap:10px">'
       f'<div style="width:22px;height:22px;border-radius:6px;background:{MINT};display:grid;place-items:center;'
       f'color:#0E1013;font-weight:600;font-size:13px">P</div><div style="font-size:17px;font-weight:600;'
       f'letter-spacing:-0.01em">PayGuard</div><div style="font-family:\'IBM Plex Mono\',monospace;font-size:10px;'
       f'color:{MUTED};border:1px solid #2A2F37;border-radius:4px;padding:1px 5px">AI</div></div>'
       f'<div style="font-size:13px;color:{MUTED}">Compensation audit agent</div></div>')

    with st.container(border=True, key="card_dataset"):
        if state == "loading":
            md(theme.status_card("Dataset", ss.pending["name"], "Running audit…", "#E3B54F"))
            st.button("Auditing…", disabled=True, key="ds_btn", width="stretch")
        elif state == "error":
            md(theme.status_card("Dataset", ss.error["name"], "Load failed: " + ss.error["short"],
                                 "#E8735F"))
            st.button("Choose another file", type="primary", key="ds_btn", width="stretch", on_click=set_state,
                      kwargs={"app_state": "empty"})
        elif state in ("loaded", "clean"):
            a = ss.audit
            s = a["summary"]
            notes = []
            if s["skipped_missing_salary"]:
                notes.append(f"{plural(s['skipped_missing_salary'], 'row')} skipped: MonthlyIncome is empty.")
            if s["skipped_invalid"]:
                notes.append(f"{plural(s['skipped_invalid'], 'row')} skipped: blank or non-numeric values.")
            if s["duplicate_ids"]:
                notes.append(f"{plural(s['duplicate_ids'], 'duplicate EmployeeNumber row')} ignored.")
            md(theme.status_card("Dataset", a["name"], f"{a['rows']:,} rows · {a['cols']} columns\n"
                                 f"Audited {fmt_dt(a['at'])}", MINT, "\n".join(notes)))
            st.button("Re-run audit", key="ds_btn", width="stretch", on_click=start_audit,
                      args=(ss.source["name"], ss.source["bytes"]))
            with st.container(key="upload_side"):
                st.file_uploader("Load another file", key=f"up_side_{ss.get('up_n', 0)}", on_change=on_upload,
                                 args=(f"up_side_{ss.get('up_n', 0)}",), label_visibility="collapsed")
        else:
            md(theme.status_card("Dataset", "No dataset loaded",
                                 "Load a CSV export from your HRIS or payroll system.", "#6F7682"))
            st.button("Load dataset", type="primary", key="ds_btn", width="stretch", on_click=load_sample)

    label, desc, dot = AI_CARD[ss.ai_mode]
    if ss.ai_mode == "offline" and ss.ai_error in OFFLINE_REASON:
        desc = OFFLINE_REASON[ss.ai_error] + " Dashboard and lookup still work."
    with st.container(border=True, key="card_ai"):
        md(f'<div style="display:flex;flex-direction:column;gap:8px"><div class="pg-mono">Assistant</div>'
           f'<div style="display:flex;align-items:center;gap:8px"><span style="width:7px;height:7px;border-radius:50%;'
           f'background:{dot}"></span><span style="font-size:13px;font-weight:500">{label}</span></div>'
           f'<div class="pg-meta">{esc(desc)}</div></div>')
    md(f'<div style="font-size:11.5px;color:{FAINT};line-height:1.55">Source: IBM HR Analytics Employee Attrition. '
       f'Names are synthetic. Exposure figures are estimates, not legal findings.</div>')


AI_CARD = {
    "demo": ("Demo mode", "Answers come from built-in rules. Add OPENAI_API_KEY to .env and restart for "
                          "open-ended questions.", "#E3B54F"),
    "connected": ("Connected", "OpenAI answers are grounded in the current audit run.", MINT),
    "offline": ("Unavailable", "OpenAI rejected the key (401). Check OPENAI_API_KEY. Dashboard and lookup still work.",
                "#E8735F"),
}
OFFLINE_REASON = {
    "timeout": "OpenAI did not respond (timeout).",
    "error": "The OpenAI request failed. Check OPENAI_API_KEY and the openai/httpx versions.",
}
AI_BANNER = {
    "demo": ("Demo mode.", "Answers come from built-in rules on your local data. Add OPENAI_API_KEY to .env and "
                           "restart for open-ended questions."),
    "connected": ("Connected.", "Answers are grounded in the current audit run and link to the employees they mention."),
    "offline": ("Assistant unavailable.", "OpenAI rejected the API key (401). Fix OPENAI_API_KEY in .env and restart. "
                                          "Everything else still works."),
}


# ---------- Header actions ----------

def header_actions():
    has_flags = ss.app_state == "loaded"
    with st.container(horizontal=True, vertical_alignment="center", gap="medium", width="content", key="hdr"):
        st.toggle("Hide salaries", key="masked", help="Hides individual salaries on screen. Exports are unaffected.")
        st.download_button("Export flagged CSV", data=flagged_csv() if has_flags else b"",
                           file_name="payguard_flagged.csv", mime="text/csv", disabled=not has_flags, key="export")


# ---------- Empty / error states ----------

def view_empty():
    cols = "".join(f'<span style="font-family:\'IBM Plex Mono\',monospace;font-size:12px;padding:4px 8px;'
                   f'border-radius:6px;background:#171A20;border:1px solid #22262D;color:{SOFT}">{c}</span>'
                   for c in REQUIRED_COLUMNS)
    with st.container(border=True, key="card_empty"):
        md(f'<div style="display:flex;flex-direction:column;gap:20px">'
           f'<div style="display:flex;flex-direction:column;gap:8px"><h1>Load an HR export to start an audit</h1>'
           f'<p style="margin:0;color:{MUTED};font-size:14px;line-height:1.6">PayGuard groups employees into cohorts by '
           f'role, level and department, then checks each person against four pay rules. Files are processed locally; '
           f'nothing is sent to OpenAI unless the assistant is connected.</p></div>'
           f'<div style="display:flex;flex-direction:column;gap:8px"><div class="pg-mono">Required columns</div>'
           f'<div style="display:flex;flex-wrap:wrap;gap:6px">{cols}</div></div></div>')
        with st.container(horizontal=True, vertical_alignment="center", key="big_row_empty"):
            st.button("Load sample dataset (1,470 rows)", type="primary", on_click=load_sample, key="load_sample")
            with st.container(key="upload"):
                st.file_uploader("Upload CSV", key=f"up_empty_{ss.get('up_n', 0)}", on_change=on_upload,
                                 args=(f"up_empty_{ss.get('up_n', 0)}",),
                                 label_visibility="collapsed")


def view_error():
    err = ss.error
    has_prev = "audit" in ss
    msg = err["message"] + (" Your previous results were not changed." if has_prev else "")
    rows = []
    for c in err["checks"]:
        icon, color = {"found": ("✓", MINT), "warning": ("!", AMBER), "missing": ("×", SEV["High"]["c"])}[c["status"]]
        rows.append(f'<div style="display:flex;align-items:center;gap:10px;font-size:13px">'
                    f'<span style="width:16px;text-align:center;color:{color}">{icon}</span>'
                    f'<span style="font-family:\'IBM Plex Mono\',monospace;color:{TEXT};min-width:190px">{esc(c["col"])}</span>'
                    f'<span style="color:{MUTED}">{esc(c["note"])}</span></div>')
    with st.container(border=True, key="card_error"):
        md(f'<div style="display:flex;flex-direction:column;gap:20px"><div style="display:flex;flex-direction:column;gap:6px">'
           f'<h1 style="font-size:20px !important">Couldn\'t audit {esc(err["name"])}</h1>'
           f'<div style="font-size:14px;color:{SOFT};line-height:1.6">{esc(msg)}</div></div>'
           f'<div style="display:flex;flex-direction:column;gap:8px">{"".join(rows)}</div></div>')
        with st.container(horizontal=True, vertical_alignment="center", key="big_row_error"):
            with st.container(key="upload_alt"):
                st.file_uploader("Choose another file", key=f"up_error_{ss.get('up_n', 0)}", on_change=on_upload,
                                 args=(f"up_error_{ss.get('up_n', 0)}",), label_visibility="collapsed")
            st.download_button("Download template CSV", data=",".join(REQUIRED_COLUMNS).encode() + b"\n",
                               file_name="payguard_template.csv", mime="text/csv", key="tmpl")
            if has_prev:
                prev = "loaded" if len(ss.audit["res"].flags) else "clean"
                st.button("Back to previous results", key="back_prev", on_click=set_state,
                          kwargs={"app_state": prev})


# ---------- Dashboard ----------

def rules_chart(res) -> None:
    f = res.flags
    rows = []
    for k in RULE_NAMES:
        for sv in SEV_ORDER:
            n = int(((f["rule"] == k) & (f["severity"] == sv)).sum()) if not f.empty else 0
            rows.append({"rule": k, "rule_name": RULE_NAMES[k], "sev": sv, "rank": SEV_RANK[sv], "count": n})
    data = pd.DataFrame(rows)
    totals = data.groupby("rule", sort=False)["count"].sum().reset_index()
    top = max(1, int(totals["count"].max()))
    totals["label"] = [f"{RULE_NAMES[k]}  ·  {RULE_DESC[k]}" for k in totals["rule"]]
    totals["zero"], totals["top"] = 0, top

    y = alt.Y("rule:N", sort=list(RULE_NAMES), axis=None, scale=alt.Scale(paddingInner=0.62, paddingOuter=0.3))
    xs = alt.Scale(domain=[0, top], nice=False)
    track = alt.Chart(totals).mark_bar(size=10, color="#1D2128", cornerRadius=3).encode(
        y=y, x=alt.X("top:Q", scale=xs, axis=None))
    pick = alt.selection_point(name="pick", fields=["rule"], on="click")
    bars = alt.Chart(data[data["count"] > 0]).mark_bar(size=10, cursor="pointer").encode(
        y=y, x=alt.X("count:Q", stack="zero", scale=xs, axis=None),
        color=alt.Color("sev:N", legend=None,
                        scale=alt.Scale(domain=SEV_ORDER, range=[SEV[s]["bar"] for s in SEV_ORDER])),
        order=alt.Order("rank:Q", sort="descending"),
        tooltip=[alt.Tooltip("rule_name:N", title="Rule"), alt.Tooltip("sev:N", title="Severity"),
                 alt.Tooltip("count:Q", title="Flags")],
    ).add_params(pick)
    text = dict(baseline="bottom", dy=-9, color=TEXT)
    names = alt.Chart(totals).mark_text(align="left", fontSize=13.5, fontWeight=500, font="IBM Plex Sans", **text
                                        ).encode(y=y, x=alt.X("zero:Q", scale=xs, axis=None), text="label:N")
    nums = alt.Chart(totals).mark_text(align="right", fontSize=13, font="IBM Plex Mono", **text
                                       ).encode(y=y, x=alt.X("top:Q", scale=xs, axis=None), text="count:Q")
    chart = (alt.layer(track, bars, names, nums).properties(height=200, background="transparent")
             .configure_view(strokeWidth=0))
    ev = st.altair_chart(chart, width="stretch", theme=None, on_select="rerun", selection_mode="pick",
                         key=f"rules_chart_{ss.chart_v}")
    picked = ev.selection.get("pick") or [] if ev else []
    if picked and picked[0].get("rule") in RULE_NAMES:
        ss.f_rule, ss.f_limit = picked[0]["rule"], PAGE
        ss.chart_v += 1   # remount without the selection so the same bar can be clicked again


def view_dashboard():
    a = ss.audit
    res, s = a["res"], a["summary"]
    clean = ss.app_state == "clean"
    emp = res.employees

    md(f'<div><h1>Compensation audit</h1><div class="pg-sub-h">Run {fmt_dt(a["at"])} · {s["cohorts"]} cohorts · '
       f'thresholds: default</div></div>')

    high_ids = set(res.flags.loc[res.flags["severity"] == "High", "EmployeeNumber"]) if not clean else set()
    open_high = sum(1 for i in high_ids if not is_reviewed(int(i)))
    exposure = s["exposure"]
    md('<div class="pg-kpis">'
       + theme.kpi("Estimated underpayment exposure", money(exposure),
                   f"Annual cost to bring {s['exposure_people']:,} employees to cohort median and correct promotion raises",
                   SEV["High"]["c"] if exposure > 0 else TEXT, big=True)
       + theme.kpi("Flagged employees", f"{s['flagged']:,}", f"{s['flagged_pct']:.1f}% of evaluated")
       + theme.kpi("High-severity flags", f"{s['high_flags']:,}",
                   f"{open_high:,} {'person' if open_high == 1 else 'people'} not yet reviewed",
                   SEV["High"]["c"] if s["high_flags"] else TEXT)
       + theme.kpi("Paid above band", money(s["above_band_total"]),
                   f"{s['above_band_people']:,} people over p75 · not in exposure")
       + "</div>")

    dq = (f"{s['evaluated']:,} of {s['total_rows']:,} employees evaluated. "
          f"{plural(s['skipped_missing_salary'], 'row')} skipped for missing salary. ")
    if s["skipped_invalid"]:
        dq += f"{plural(s['skipped_invalid'], 'row')} skipped for blank or non-numeric values. "
    if s["duplicate_ids"]:
        dq += f"{plural(s['duplicate_ids'], 'duplicate EmployeeNumber row')} ignored (first kept). "
    dq += (f"{s['excluded_small_cohort']:,} employees sit in cohorts smaller than 5 and were not compared. "
           "Salary is MonthlyIncome × 12.")
    md(theme.note(dq))

    if clean:
        md(f'<div style="border:1px solid rgba(111,211,181,0.3);background:rgba(111,211,181,0.05);border-radius:12px;'
           f'padding:32px;display:flex;flex-direction:column;gap:8px"><div style="font-size:18px;font-weight:600">'
           f'No issues found</div><div style="font-size:14px;color:{SOFT};line-height:1.6;max-width:640px">All '
           f'{s["evaluated"]:,} evaluated employees are within expected ranges for their cohort on all four rules. '
           f'Try stricter thresholds or check that salaries are annual, not monthly.</div></div>')
        return

    c1, c2 = st.columns(2, gap="small")
    with c1, st.container(border=True, key="card_rules"):
        md(f'<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">'
           f'<div style="font-size:15px;font-weight:600">Flags by rule</div>{theme.legend()}</div>')
        rules_chart(res)
    with c2, st.container(border=True, key="card_dept"):
        flagged = emp[emp["flag_count"] > 0]
        rows = ""
        for d, head in emp["Department"].value_counts().items():
            fl = flagged[flagged["Department"] == d]
            rows += (f'<tr><td>{esc(str(d))}</td><td style="color:{SOFT}">{head:,}</td>'
                     f'<td>{len(fl):,} <span style="color:{FAINT}">({len(fl) / head * 100:.1f}%)</span></td>'
                     f'<td>{money(fl["exposure"].sum())}</td></tr>')
        md(f'<div style="font-size:15px;font-weight:600;margin-bottom:12px">By department</div>'
           f'<div style="overflow-x:auto"><table class="pg-dept"><thead><tr><th>Department</th><th>Headcount</th>'
           f'<th>Flagged</th><th>Exposure</th></tr></thead><tbody>{rows}</tbody></table></div>')

    flagged_table(res)


def flagged_table(res):
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        md("<h2>Flagged employees</h2>", width="content")
        st.text_input("Filter", key="f_q", placeholder="Filter by name, ID or role", label_visibility="collapsed",
                      live=True, width=260, on_change=set_state, kwargs={"f_limit": PAGE})

    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        chips("f_sev", {"All": "All severities", **{s: s for s in SEV_ORDER}}, f_limit=PAGE)
        md('<div class="pg-vr"></div>', width="content")
        chips("f_rule", {"All": "All rules", **RULE_SHORT}, f_limit=PAGE)

    e = res.employees[res.employees["flag_count"] > 0]
    total = len(e)
    if ss.f_sev != "All" or ss.f_rule != "All":
        # Like the reference: the employee needs some flag of that severity and some flag of that rule.
        ids = set(res.flags.loc[res.flags["severity"] == ss.f_sev, "EmployeeNumber"]) if ss.f_sev != "All" else None
        rids = set(res.flags.loc[res.flags["rule"] == ss.f_rule, "EmployeeNumber"]) if ss.f_rule != "All" else None
        keep = ids if rids is None else rids if ids is None else ids & rids
        e = e[e["EmployeeNumber"].isin(keep)]
    q = (ss.get("f_q") or "").strip().lower()
    if q:
        e = e[e[COL_NAME].astype(str).str.lower().str.contains(q, regex=False)
              | (e["EmployeeNumber"].astype(str) == q.lstrip("#"))
              | e["JobRole"].astype(str).str.lower().str.contains(q, regex=False)]

    keys = {"impact": e["exposure"], "salary": e["AnnualSalary"], "gap": e["ratio"], "name": e[COL_NAME].astype(str).str.lower(),
            "sev": e["top_severity"].map(SEV_RANK) * 1e9 + e["exposure"]}
    e = e.assign(_k=keys[ss.f_sort]).sort_values("_k", ascending=ss.f_dir > 0, kind="stable")

    heads = [("Severity", "sev", ""), ("Employee", "name", ""), ("Role", None, ""), ("Department", None, ""),
             ("Salary", "salary", "r"), ("vs median", "gap", "r"), ("Flags", None, ""),
             ("Est. adjustment", "impact", "r"), ("Status", None, "")]
    th = ""
    for label, k, cls in heads:
        arrow = (" ↑" if ss.f_dir > 0 else " ↓") if ss.f_sort == k else ""
        act = f' data-act="sort" data-val="{k}"' if k else ""
        th += f'<th class="{cls}"{act}>{label}{arrow}</th>'
    body = ""
    for r in e.head(ss.f_limit).itertuples():
        eid = int(r.EmployeeNumber)
        sv = r.top_severity
        rev = is_reviewed(eid)
        gap = pct(r.ratio) if masked else f"{money(r.gap)} ({pct(r.ratio)})"
        body += (
            f'<tr data-act="open" data-val="{eid}" tabindex="0" class="{"rev" if rev else ""}">'
            f'<td><div class="sev"><span class="dot" style="background:{SEV[sv]["bar"]}"></span>'
            f'<span style="font-size:12.5px;color:{SEV[sv]["c"]}">{sv}</span></div></td>'
            f'<td><div class="nw" style="font-weight:500">{esc(r.Name)}</div><div class="mono muted" style="font-size:11.5px">#{eid}</div></td>'
            f'<td class="soft nw">{esc(r.JobRole)} <span class="muted">· L{int(r.JobLevel)}</span></td>'
            f'<td class="soft nw">{esc(r.Department)}</td>'
            f'<td class="r nw">{money(r.AnnualSalary, masked)}</td>'
            f'<td class="r nw" style="color:{SEV["High"]["c"] if r.ratio < 1 else SEV["Low"]["c"]}">{gap}</td>'
            f'<td>{theme.chips([(f.rule, f.severity) for f in flags_of(eid)])}</td>'
            f'<td class="r nw">{money(r.exposure, masked) if r.exposure else "—"}</td>'
            f'<td class="nw" style="font-size:12.5px;color:{MINT if rev else MUTED}">{"Reviewed" if rev else "Open"}</td></tr>')
    empty = "" if len(e) else '<div class="empty">No flagged employees match these filters.</div>'
    ev = html_block(f'<div class="wrap"><table style="min-width:960px"><thead><tr>{th}</tr></thead>'
                    f'<tbody>{body}</tbody></table>{empty}</div>', key="tbl_flagged")
    if ev and ev["act"] == "sort":
        k = ev["val"]
        ss.f_dir = -ss.f_dir if ss.f_sort == k else (1 if k in ("name", "gap") else -1)
        ss.f_sort = k
        st.rerun()
    if ev and ev["act"] == "open":
        open_profile(ev["val"])

    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                      key="pager_flag"):
        shown = min(ss.f_limit, len(e))
        md(f'<span style="font-size:12.5px;color:{MUTED}">Showing {shown:,} of {plural(len(e), "flagged employee")}'
           + (f" (filtered from {total:,})" if len(e) != total else "") + "</span>", width="content")
        if not len(e):
            st.button("Clear filters", key="link_clear_f", type="tertiary", on_click=set_state,
                      kwargs={"f_sev": "All", "f_rule": "All", "f_q": "", "f_limit": PAGE})
        elif len(e) > ss.f_limit:
            st.button("Show 25 more", key="more_f", on_click=set_state, kwargs={"f_limit": ss.f_limit + PAGE})


# ---------- Employees ----------

def view_employees():
    res = ss.audit["res"]
    emp = res.employees
    clean = ss.app_state == "clean"
    md("<h1>Employees</h1>")
    st.text_input("Search", key="e_q", placeholder="Search name, employee ID, role or department",
                  label_visibility="collapsed", live=True, on_change=set_state, kwargs={"e_page": 0})
    depts = [str(d) for d in emp["Department"].value_counts().index]
    if ss.e_dept not in depts:
        ss.e_dept = "All"
    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        chips("e_dept", {"All": "All departments", **{d: d for d in depts}}, e_page=0)
        md('<div class="pg-vr"></div>', width="content")
        chips("e_flagged", {"Flagged only": "Flagged only"}, e_page=0)

    e = emp
    if ss.e_dept != "All":
        e = e[e["Department"] == ss.e_dept]
    if ss.e_flagged:
        e = e[e["flag_count"] > 0] if not clean else e.iloc[0:0]
    q = (ss.get("e_q") or "").strip().lower()
    if q:
        e = e[e[COL_NAME].astype(str).str.lower().str.contains(q, regex=False)
              | (e["EmployeeNumber"].astype(str) == q.lstrip("#"))
              | e["JobRole"].astype(str).str.lower().str.contains(q, regex=False)
              | e["Department"].astype(str).str.lower().str.contains(q, regex=False)]
    e = e.sort_values("AnnualSalary", ascending=False, na_position="last", kind="stable")

    pages = max(1, -(-len(e) // PAGE))
    page = min(ss.e_page, pages - 1)
    body = ""
    for r in e.iloc[page * PAGE:(page + 1) * PAGE].itertuples():
        eid = int(r.EmployeeNumber)
        if r.missing_salary:
            sal = f'<span style="color:{AMBER}">Missing</span>'
        else:
            sal = money(r.AnnualSalary, masked)
        fl = flags_of(eid)
        if fl and not clean:
            tags = theme.chips([(f.rule, f.severity) for f in fl])
        elif r.excluded or r.invalid:
            tags = theme.chip("Not evaluated")
        else:
            tags = ""
        body += (f'<tr data-act="open" data-val="{eid}" tabindex="0">'
                 f'<td class="mono" style="font-size:12.5px;color:{MUTED}">{eid}</td>'
                 f'<td class="nw" style="font-weight:500">{esc(r.Name)}</td>'
                 f'<td class="soft nw">{esc(str(r.JobRole))} <span class="muted">· L{n_(r.JobLevel)}</span></td>'
                 f'<td class="soft nw">{esc(str(r.Department))}</td>'
                 f'<td class="r nw">{sal}</td>'
                 f'<td class="r nw soft">{n_(r.YearsAtCompany)} yrs</td><td>{tags}</td></tr>')
    empty = ""
    if not len(e):
        what = f"“{esc(ss.get('e_q') or '')}”" if q else "these filters"
        empty = (f'<div class="empty"><div>No employees match {what}.</div><div style="font-size:12.5px;color:{FAINT}">'
                 f'Search covers name, ID, role and department. IDs match exactly.</div></div>')
    ev = html_block(
        f'<div class="wrap"><table style="min-width:860px"><thead><tr><th>ID</th><th>Name</th><th>Role</th>'
        f'<th>Department</th><th class="r">Salary</th><th class="r">Tenure</th><th>Flags</th></tr></thead>'
        f'<tbody>{body}</tbody></table>{empty}</div>', key="tbl_emp")
    if ev and ev["act"] == "open":
        open_profile(ev["val"])

    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                      key="pager_emp"):
        rng = f"{page * PAGE + 1:,}–{min(len(e), (page + 1) * PAGE):,} of {len(e):,}" if len(e) else "0 results"
        md(f'<span style="font-size:12.5px;color:{MUTED}">{rng} · Click a row to open the profile</span>',
           width="content")
        if not len(e):
            st.button("Clear search and filters", key="link_clear_e", type="tertiary", on_click=set_state,
                      kwargs={"e_q": "", "e_dept": "All", "e_flagged": None, "e_page": 0})
        else:
            with st.container(horizontal=True, width="content", gap="small"):
                st.button("Previous", key="e_prev", disabled=page == 0, on_click=set_state, kwargs={"e_page": page - 1})
                st.button("Next", key="e_next", disabled=page >= pages - 1, on_click=set_state,
                          kwargs={"e_page": page + 1})


# ---------- Ask PayGuard ----------

SUGGESTIONS = [
    "Who are the top 3 most underpaid employees?",
    "Show me employees promoted without a raise",
    "Is there salary compression in any department?",
]


def view_ask():
    with st.container(key="ask_col"):
        _view_ask()


def _view_ask():
    mode = ss.ai_mode
    offline = mode == "offline"
    pending = ss.chat_pending is not None
    md("<h1>Ask PayGuard</h1>")
    title, text = AI_BANNER[mode]
    if offline and ss.ai_error in OFFLINE_REASON:
        text = OFFLINE_REASON[ss.ai_error] + " Fix it and restart. Everything else still works."
    theme.banner(mode, title, text)

    parts = []
    if not ss.msgs:
        dis = " disabled" if offline else ""
        parts.append('<div class="sugs">' + "".join(
            f'<button class="sug" data-act="ask" data-val="{esc(sg)}"{dis}>{esc(sg)}</button>' for sg in SUGGESTIONS)
            + "</div>")
    for m in ss.msgs:
        if m["role"] == "user":
            parts.append(f'<div class="msg user"><div class="bubble">{esc(m["text"])}</div></div>')
            continue
        body = theme.mask_text(m["text"], masked)
        rows = ""
        for r in m.get("rows", []):
            inner = (f'<span><span style="font-weight:500">{esc(r["a"])}</span> <span class="muted">{esc(r["b"])}</span></span>'
                     f'<span style="font-variant-numeric:tabular-nums;color:{TONE[r["tone"]]}">{esc(r["c"])}</span>')
            rows += (f'<button class="arow" data-act="open" data-val="{r["id"]}">{inner}</button>' if r.get("id")
                     else f'<div class="arow">{inner}</div>')
        parts.append(f'<div class="msg"><div class="bubble">{esc(body)}</div>'
                     + (f'<div class="arows">{rows}</div>' if rows else "")
                     + (f'<div class="foot">{esc(m["foot"])}</div>' if m.get("foot") else "") + "</div>")
    if pending:
        parts.append('<div class="thinking">Checking audit results…</div>')
    ev = html_block(f'<div class="chat">{"".join(parts)}</div>', key="chat_log")
    # Native chat input: Send is disabled while empty, 500-char limit with counter, and it locks while a
    # reply is pending.
    typed = st.chat_input("Assistant unavailable" if offline else
                          "Ask about a flag, an employee (name or #ID), or a cohort",
                          key="chat_in", max_chars=500, disabled=offline or pending, submit_mode="disable")
    md('<div class="pg-caption" style="font-size:11.5px;color:#8A919C">Answers use the current audit run only. '
       'Verify before acting on pay.</div>')
    if ev and ev["act"] == "open" and ev.get("val"):
        open_profile(ev["val"])
    question = typed or (ev["val"] if ev and ev["act"] == "ask" else None)
    if question and not offline and not pending:
        ss.msgs.append({"role": "user", "text": str(question).strip()[:500]})
        ss.chat_pending = ss.msgs[-1]["text"]
        st.rerun()


def answer_pending():
    q = ss.chat_pending
    res = ss.audit["res"]
    if ss.ai_mode == "connected":
        ans, ss.llm_history = agent.respond(q, ss.llm_history, res, footnote())
        if ans.get("error") in ("auth", "timeout"):
            ss.ai_mode, ss.ai_error = "offline", ans["error"]
    else:
        ans = demo_agent.answer(q, res, footnote())
    ss.msgs.append({"role": "assistant", **ans})
    ss.chat_pending = None
    st.rerun()


# ---------- Raw data ----------

HEADERS = {"EmployeeNumber": "Employee ID", "AnnualSalary": "Annual salary", "PercentSalaryHike": "Last raise %",
           "YearsSinceLastPromotion": "Yrs since promotion", "JobLevel": "Job level", "JobRole": "Job role",
           "MonthlyIncome": "Monthly income", "BusinessTravel": "Business travel", "OverTime": "Overtime",
           "Over18": "Over 18", "YearsWithCurrManager": "Yrs with current manager",
           "YearsInCurrentRole": "Yrs in current role", "YearsAtCompany": "Years at company",
           "NumCompaniesWorked": "Companies worked", "TotalWorkingYears": "Total working years",
           "TrainingTimesLastYear": "Trainings last year", "StockOptionLevel": "Stock option level"}
CHIP_LABEL = {"AnnualSalary": "MonthlyIncome×12"}
DEFAULT_COLS = ["EmployeeNumber", "Name", "Attrition", "Department", "JobRole", "JobLevel", "AnnualSalary",
                "YearsAtCompany", "YearsSinceLastPromotion", "PercentSalaryHike"]
PAY_COLS = {"AnnualSalary", "MonthlyIncome", "MonthlyRate", "DailyRate", "HourlyRate"}


def human(col: str) -> str:
    if col in HEADERS:
        return HEADERS[col]
    words = "".join(f" {ch}" if ch.isupper() else ch for ch in col).split()
    return " ".join([words[0]] + [w.lower() for w in words[1:]]) if words else col


def view_raw():
    a = ss.audit
    raw = a["raw"].copy()
    if "AnnualSalary" not in raw.columns:
        raw.insert(raw.columns.get_loc("MonthlyIncome") + 1, "AnnualSalary",
                   pd.to_numeric(raw["MonthlyIncome"], errors="coerce") * 12)
    all_cols = [c for c in ["EmployeeNumber", COL_NAME] if c in raw.columns] + \
               [c for c in raw.columns if c not in ("EmployeeNumber", COL_NAME)]
    # Keep the chip selection valid if a new file has different columns.
    ss.r_cols = [c for c in (ss.r_cols if ss.r_cols is not None else DEFAULT_COLS) if c in all_cols]
    vis = [c for c in all_cols if c in ss.r_cols]
    numeric = {c for c in vis if pd.api.types.is_numeric_dtype(raw[c])}

    def cell(c, v):
        if pd.isna(v) or (isinstance(v, str) and not v.strip()):
            return None
        if c in PAY_COLS:
            return money(float(v), masked) if isinstance(v, (int, float)) else str(v)
        if c == "PercentSalaryHike" and isinstance(v, (int, float)):
            return f"{v:g}%"
        return f"{v:g}" if isinstance(v, float) else str(v)

    shown = pd.DataFrame({c: [cell(c, v) for v in raw[c]] for c in vis}, index=raw.index)
    q = (ss.get("r_q") or "").strip().lower()
    if q and vis:
        hit = pd.Series(False, index=shown.index)
        for c in vis:
            hit |= shown[c].fillna("").str.lower().str.contains(q, regex=False)
        shown = shown[hit]

    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="bottom"):
        md(f'<div><h1>Raw data</h1><div class="pg-sub-h">{esc(a["name"])} · showing {len(vis)} of '
           f'{len(all_cols)} columns</div></div>', width="content")
        st.download_button("Download filtered CSV", key="raw_dl", file_name="payguard_raw_filtered.csv",
                           mime="text/csv", disabled=not vis,
                           data=raw.loc[shown.index, vis].to_csv(index=False).encode())
    st.text_input("Search", key="r_q", placeholder="Search any visible column", label_visibility="collapsed",
                  live=True, on_change=set_state, kwargs={"r_page": 0})
    chips("r_cols", {c: CHIP_LABEL.get(c, c) for c in all_cols}, multi=True, r_page=0)

    pages = max(1, -(-len(shown) // PAGE))
    page = min(ss.r_page, pages - 1)
    if not vis:
        md('<div class="pg-raw"><div class="pg-empty">All columns are hidden. Turn one on above.</div></div>')
    elif not len(shown):
        md(f'<div class="pg-raw"><div class="pg-empty">No rows contain “{esc(ss.get("r_q") or "")}”.</div></div>')
    else:
        th = "".join(f'<th style="text-align:{"right" if c in numeric else "left"}">{esc(human(c))}</th>' for c in vis)
        trs = ""
        for _, row in shown.iloc[page * PAGE:(page + 1) * PAGE].iterrows():
            tds = ""
            for c in vis:
                v = row[c]
                align = "right" if c in numeric else "left"
                tds += (f'<td style="text-align:{align};color:{AMBER}">missing</td>' if v is None
                        else f'<td style="text-align:{align}">{esc(v)}</td>')
            trs += f"<tr>{tds}</tr>"
        md(f'<div class="pg-raw"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>')

    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                      key="pager_raw"):
        rng = f"{page * PAGE + 1:,}–{min(len(shown), (page + 1) * PAGE):,} of {len(shown):,} rows" \
            if len(shown) and vis else "0 rows"
        md(f'<span style="font-size:12.5px;color:{MUTED}">{rng}</span>', width="content")
        with st.container(horizontal=True, width="content", gap="small"):
            st.button("Previous", key="r_prev", disabled=page == 0, on_click=set_state, kwargs={"r_page": page - 1})
            st.button("Next", key="r_next", disabled=page >= pages - 1 or not vis, on_click=set_state,
                      kwargs={"r_page": page + 1})


# ---------- Profile dialog ----------

def profile(eid: int):
    res = ss.audit["res"]
    emp = res.employees
    hit = emp[emp["EmployeeNumber"] == eid]
    if hit.empty:
        return
    e = hit.iloc[0]

    @st.dialog(str(e[COL_NAME]), position="right", on_dismiss=close_profile)
    def _show():
        clean = ss.app_state == "clean"
        fl = [] if clean else flags_of(eid)
        evald = bool(e["evaluated"])
        md(f'<div style="font-size:13px;color:{MUTED};line-height:1.5;margin-top:-10px">'
           f'<span class="pg-mono" style="font-size:13px;text-transform:none;letter-spacing:0;color:{MUTED}">#{eid}</span>'
           f' · {esc(str(e["JobRole"]))} · L{n_(e["JobLevel"])} · {esc(str(e["Department"]))}</div>')

        notes = []
        if (emp[COL_NAME] == e[COL_NAME]).sum() > 1:
            notes.append(f"More than one employee is named {e[COL_NAME]}. Confirm by ID #{eid} before acting.")
        if str(e.get("Attrition", "")).strip().lower() == "yes":
            notes.append("Attrition is “Yes” in the source data. This person may no longer be employed.")
        if e["missing_salary"]:
            notes.append("Salary is missing in the source file, so this employee was not evaluated.")
        elif e["invalid"]:
            notes.append("Some required values are blank or non-numeric, so this employee was not evaluated.")
        if e["excluded"]:
            n = 0 if pd.isna(e["n"]) else int(e["n"])
            notes.append(f"Only {n} {'person shares' if n == 1 else 'people share'} this role, level and department. "
                         "Cohorts under 5 are not compared, to avoid unreliable medians and re-identification.")
        if notes:
            md('<div style="display:flex;flex-direction:column;gap:8px">'
               + "".join(f'<div class="pg-warn">{esc(t)}</div>' for t in notes) + "</div>")

        if evald:
            gap = (f"{pct(e['ratio'])} vs cohort median" if masked
                   else f"{money(e['gap'])} ({pct(e['ratio'])}) vs cohort median")
            gap_color = SEV["High"]["c"] if e["ratio"] < 0.88 else MUTED
        else:
            gap, gap_color = "Not compared to a cohort", MUTED
        md(f'<div style="display:flex;flex-direction:column;gap:4px"><div style="font-size:12.5px;color:{MUTED}">'
           f'Annual salary</div><div style="font-size:30px;font-weight:600;font-variant-numeric:tabular-nums">'
           f'{money(e["AnnualSalary"], masked)}</div><div style="font-size:13px;color:{gap_color}">{gap}</div></div>')

        if evald:
            dot = SEV[e["top_severity"]]["bar"] if fl else MINT
            label = f"{e['JobRole']} L{int(e['JobLevel'])}, {e['Department']} · n={int(e['n'])}"
            md(theme.cohort_band(e["AnnualSalary"], e["min"], e["p25"], e["median"], e["p75"], e["max"], dot,
                                 label, masked))

        cards = ""
        for f in fl:
            impact = (f'<div style="font-size:12.5px;color:{MUTED}">Est. adjustment <span style="color:{TEXT};'
                      f'font-variant-numeric:tabular-nums">{money(f.impact, masked)}</span> / year</div>'
                      if f.impact > 0 else "")
            cards += (f'<div class="pg-flag"><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
                      f'<span class="pg-chip" style="margin:0;background:{SEV[f.severity]["bg"]};color:{SEV[f.severity]["c"]}">'
                      f'{f.severity}</span><span style="font-size:13.5px;font-weight:500">{RULE_NAMES[f.rule]}</span></div>'
                      f'<div style="font-size:13px;color:{SOFT};line-height:1.55">{esc(theme.mask_text(f.reason, masked))}</div>'
                      f'{impact}</div>')
        if not fl:
            cards = (f'<div style="font-size:13px;color:{MUTED};margin-top:10px">'
                     + ("No flags. Pay is within the expected range for this cohort." if evald else "Not evaluated.")
                     + "</div>")
        md(f'<div><div style="font-size:13px;font-weight:500">Flags</div>{cards}</div>')

        promo = e["YearsSinceLastPromotion"]
        years = lambda v: "—" if pd.isna(v) else f"{n_(v)} year{'' if v == 1 else 's'}"
        facts = [("Tenure", years(e["YearsAtCompany"])),
                 ("Since last promotion", "Under 1 year" if promo == 0 else years(promo)),
                 ("Last raise", f"{n_(e['PercentSalaryHike'])}%" if pd.notna(e["PercentSalaryHike"]) else "—"),
                 ("Age", n_(e["Age"]) if "Age" in e else "—")]
        md('<div class="pg-facts">' + "".join(
            f'<div><span style="font-size:11.5px;color:{FAINT}">{k}</span>'
            f'<span style="font-size:14px;font-variant-numeric:tabular-nums">{esc(v)}</span></div>' for k, v in facts)
           + "</div>")

        summary_txt = (f"{e[COL_NAME]} (#{eid}) · {e['JobRole']} L{n_(e['JobLevel'])} · {e['Department']}\n"
                       + ("\n".join(f"- {f.severity}: {RULE_NAMES[f.rule]}. {f.reason}" for f in fl) if fl else "No flags."))
        rev = is_reviewed(eid)
        review_btn = (f'<button class="btn {"quiet" if rev else "primary"}" data-act="review" data-val="{eid}">'
                      f'{"Reopen" if rev else "Mark reviewed"}</button>' if fl else "")
        ev = html_block(f'<div class="actions">{review_btn}<button class="btn" data-copy="{esc(summary_txt)}">'
                        f'Copy summary</button></div>', key=f"prof_actions_{eid}")
        if ev and ev["act"] == "review":
            ss.reviewed[eid] = not rev
            st.rerun()   # full rerun so tables and KPIs update; the drawer stays open (profile_id is still set)

    _show()


# ---------- Page ----------

def state_panel():
    {"empty": view_empty, "loading": run_loading, "error": view_error}[ss.app_state]()


with st.sidebar:
    sidebar()

header_actions()
state = ss.app_state
has_data = state in ("loaded", "clean")
flagged_n = ss.audit["summary"]["flagged"] if state == "loaded" else 0
labels = [f"Dashboard `{flagged_n:,}`" if flagged_n else "Dashboard", "Employees", "Ask PayGuard", "Raw data"]
views = [view_dashboard, view_employees, view_ask, view_raw] if has_data else [state_panel] * 4
# Tabs track which one is open, so only that tab's content runs.
for tab, view in zip(st.tabs(labels, key="tab", on_change="rerun"), views):
    if tab.open:
        with tab:
            view()

if has_data and ss.profile_id is not None:
    profile(ss.profile_id)
if has_data and ss.chat_pending is not None:
    answer_pending()
