"""PayGuard AI — Streamlit UI (Stream C). Tabs 1 + 3; tab 2 is a Stream D placeholder."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from schema import (
    COL_ANNUAL_SALARY, COL_COHORT, COL_DEPT, COL_ID, COL_INCOME_MONTHLY,
    COL_LEVEL, COL_NAME, COL_ROLE, RULE_META, SEVERITY_COLOR, SEVERITY_HIGH,
    SEVERITY_RANK, synthesize_name,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

MOCK_FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "expected_flags.json"
DARK = dict(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117", font_color="#E6EDF3")


# ---------- Data loading ----------

def _mock_employees() -> pd.DataFrame:
    from schema import DATA_PATH
    df = pd.read_csv(DATA_PATH)
    df[COL_ANNUAL_SALARY] = (df[COL_INCOME_MONTHLY] * 12).astype(int)
    df[COL_NAME] = df[COL_ID].apply(synthesize_name)
    df[COL_COHORT] = df[COL_ROLE].astype(str) + " L" + df[COL_LEVEL].astype(str)
    return df


def _mock_flags() -> pd.DataFrame:
    return pd.DataFrame(json.loads(MOCK_FIXTURE.read_text()))


def _mock_cohort_stats(df: pd.DataFrame) -> pd.DataFrame:
    return (df.groupby(COL_COHORT)[COL_ANNUAL_SALARY]
              .agg(["median", "count"]).reset_index()
              .rename(columns={"median": "cohort_median", "count": "cohort_size"}))


def _mock_total_exposure(flags: pd.DataFrame) -> int:
    w = {"High": 10000, "Medium": 5000, "Low": 2000}
    return int(flags["severity"].map(w).fillna(0).sum())


@st.cache_data(show_spinner="Running compensation audit...")
def load_and_detect():
    """Return (employees_df, flags_df, cohort_stats_df, total_exposure, is_mock)."""
    mock_mode = False
    try:
        import detectors  # type: ignore
        employees = detectors.load_employees()
        flags = detectors.run_all(employees)
        if not isinstance(flags, pd.DataFrame):
            flags = pd.DataFrame(flags)
        stats = detectors.cohort_stats(employees)
        exposure = int(detectors.total_exposure(flags, stats))
    except Exception:
        mock_mode = True
        employees = _mock_employees()
        flags = _mock_flags()
        stats = _mock_cohort_stats(employees)
        exposure = _mock_total_exposure(flags)

    if not flags.empty:
        join_cols = [COL_ID, COL_NAME, COL_ROLE, COL_LEVEL, COL_DEPT, COL_ANNUAL_SALARY, COL_COHORT]
        flags = flags.merge(employees[join_cols], left_on="employee_id", right_on=COL_ID, how="left")
        flags["severity_rank"] = flags["severity"].map(SEVERITY_RANK).fillna(0).astype(int)
        flags["rule_label"] = flags["rule"].map(lambda r: RULE_META.get(r, {}).get("label", r))
        flags["rule_icon"] = flags["rule"].map(lambda r: RULE_META.get(r, {}).get("icon", ""))
    return employees, flags, stats, exposure, mock_mode


def fmt_money(x) -> str:
    try:
        return f"${int(x):,}"
    except Exception:
        return "—"


# ---------- Page / state ----------

st.set_page_config(page_title="PayGuard AI", layout="wide", page_icon="🛡️")
st.session_state.setdefault("loaded", False)
st.session_state.setdefault("selected_employee_id", None)
st.session_state.setdefault("lookup_selected_id", None)


# ---------- Sidebar ----------

with st.sidebar:
    st.markdown("# PayGuard AI 🛡️")
    st.caption("AI compensation audit agent")
    if st.button("📊 Load dataset", use_container_width=True, type="primary"):
        st.session_state.loaded = True
        load_and_detect()
    st.divider()
    if os.environ.get("OPENAI_API_KEY"):
        st.success("🟢 Chat enabled")
    else:
        st.warning("🟡 Chat disabled — set OPENAI_API_KEY")
    st.divider()
    st.caption("Data: IBM HR Analytics Employee Attrition (1,470 employees)")


# ---------- Splash ----------

if not st.session_state.loaded:
    st.title("PayGuard AI")
    st.markdown(
        "Companies know *if* payroll ran. Not whether it's fair.  \n"
        "Load the dataset to see what's hiding in your comp plan."
    )
    st.stop()


# ---------- Load ----------

employees_df, flags_df, cohort_stats_df, total_exposure, is_mock = load_and_detect()
if is_mock:
    st.warning("⚠️ Running in mock mode — detector module not yet available.")

# Expose shared frames for the chat agent (Stream D).
st.session_state["full_df"] = employees_df
st.session_state["flagged_df"] = flags_df
st.session_state["stats"] = cohort_stats_df

tab_dash, tab_lookup, tab_chat, tab_raw = st.tabs(
    ["📊 Dashboard", "🔍 Employee Lookup", "💬 Ask PayGuard", "🗂️ Raw data"]
)


# ---------- Evidence panel renderer ----------

def render_flag(flag_row, employees_df):
    st.markdown(f"**{flag_row['rule_icon']} {flag_row['rule_label']}** — :red[{flag_row['severity']}]")
    st.info(flag_row["reason"])
    evidence = flag_row.get("evidence") or {}
    if isinstance(evidence, dict) and evidence:
        ev_df = pd.DataFrame(list(evidence.items()), columns=["Field", "Value"])
        st.table(ev_df)

    cohort_key = flag_row.get(COL_COHORT)
    cohort_df = employees_df[employees_df[COL_COHORT] == cohort_key]
    emp_salary = float(flag_row[COL_ANNUAL_SALARY])
    if len(cohort_df) < 2:
        return

    col_a, col_b = st.columns(2)
    with col_a:
        box = go.Figure()
        box.add_trace(go.Box(y=cohort_df[COL_ANNUAL_SALARY], name=str(cohort_key),
                             marker_color="#4A9EFF", boxmean=True))
        box.add_trace(go.Scatter(x=[str(cohort_key)], y=[emp_salary], mode="markers",
                                 marker=dict(symbol="diamond", color="#E74C3C", size=16),
                                 name=flag_row[COL_NAME]))
        box.update_layout(title=f"Cohort salary ({len(cohort_df)} employees)",
                          height=320, showlegend=False, **DARK)
        st.plotly_chart(box, use_container_width=True)
    with col_b:
        hist = px.histogram(cohort_df, x=COL_ANNUAL_SALARY, nbins=20,
                            title="Cohort histogram",
                            color_discrete_sequence=["#4A9EFF"])
        hist.add_vline(x=emp_salary, line_color="#E74C3C", line_width=3,
                       annotation_text=flag_row[COL_NAME], annotation_position="top")
        hist.update_layout(height=320, bargap=0.05, **DARK)
        st.plotly_chart(hist, use_container_width=True)


# ========== TAB 1: DASHBOARD ==========

with tab_dash:
    flagged_count = int(flags_df["employee_id"].nunique()) if not flags_df.empty else 0

    st.markdown(
        f"""
<div style="text-align:center; padding: 24px 0 8px 0;">
  <div style="font-size:14px; color:#8B949E; letter-spacing:2px; text-transform:uppercase;">
    Estimated Compensation Exposure
  </div>
  <div style="font-size:72px; font-weight:800; color:#E74C3C; line-height:1.1;">
    {fmt_money(total_exposure)}
  </div>
  <div style="font-size:14px; color:#8B949E;">across {flagged_count:,} flagged employees</div>
</div>""",
        unsafe_allow_html=True,
    )

    high_count = int((flags_df["severity"] == SEVERITY_HIGH).sum()) if not flags_df.empty else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total employees", f"{len(employees_df):,}")
    c2.metric("Flagged employees", f"{flagged_count:,}")
    c3.metric("High-severity flags", f"{high_count:,}")
    c4.metric("Cohorts analyzed", f"{len(cohort_stats_df):,}")
    st.divider()

    if not flags_df.empty:
        rule_counts = flags_df.groupby(["rule", "severity"]).size().reset_index(name="count")
        rule_counts["label"] = rule_counts["rule"].map(
            lambda r: f"{RULE_META.get(r, {}).get('icon', '')} {RULE_META.get(r, {}).get('label', r)}"
        )
        rule_counts = rule_counts.sort_values("count", ascending=True)
        fig = px.bar(rule_counts, x="count", y="label", color="severity", orientation="h",
                     color_discrete_map=SEVERITY_COLOR,
                     labels={"count": "Flags", "label": "", "severity": "Severity"},
                     title="Flags by rule")
        fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=20), **DARK)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Flagged employees")

    if flags_df.empty:
        st.info("No flags found.")
    else:
        display = flags_df.copy()
        display["Severity"] = display.apply(
            lambda r: f"{r['rule_icon']} {r['rule_label']} ({r['severity']})", axis=1)
        display["Salary"] = display[COL_ANNUAL_SALARY].apply(fmt_money)
        display = display.sort_values(["severity_rank", COL_ANNUAL_SALARY],
                                       ascending=[False, False]).reset_index(drop=True)

        table_cols = {"Severity": "Severity", COL_NAME: "Name", COL_ROLE: "Role",
                      COL_LEVEL: "Level", COL_DEPT: "Department",
                      "Salary": "Salary", "reason": "Reason"}
        shown = display[list(table_cols.keys())].rename(columns=table_cols)

        selection = st.dataframe(shown, use_container_width=True, hide_index=True,
                                 on_select="rerun", selection_mode="single-row", height=360)

        sel_rows = selection.selection.rows if selection and selection.selection else []
        if sel_rows:
            st.session_state.selected_employee_id = int(display.iloc[sel_rows[0]]["employee_id"])

        if st.session_state.selected_employee_id is not None:
            emp_id = st.session_state.selected_employee_id
            emp_flags = flags_df[flags_df["employee_id"] == emp_id]
            if not emp_flags.empty:
                first = emp_flags.iloc[0]
                st.divider()
                st.markdown(
                    f"### {first[COL_NAME]} · {first[COL_ROLE]} L{first[COL_LEVEL]} · "
                    f"**{fmt_money(first[COL_ANNUAL_SALARY])}**"
                )
                if len(emp_flags) > 1:
                    rule_tabs = st.tabs(
                        [f"{r['rule_icon']} {r['rule_label']}" for _, r in emp_flags.iterrows()]
                    )
                    for tab, (_, r) in zip(rule_tabs, emp_flags.iterrows()):
                        with tab:
                            render_flag(r, employees_df)
                else:
                    render_flag(emp_flags.iloc[0], employees_df)


# ========== TAB 2: EMPLOYEE LOOKUP ==========

def _rating_bar(val, scale: int = 4) -> str:
    try:
        v = int(val)
    except Exception:
        return "—"
    v = max(0, min(scale, v))
    return "●" * v + "○" * (scale - v) + f"  ({v}/{scale})"


with tab_lookup:
    st.subheader("Find an employee")
    query = st.text_input(
        label="Search employees",
        placeholder="Type a name, employee ID, role, or department...",
        key="lookup_query",
    )

    flag_counts = (flags_df.groupby("employee_id").size()
                   if not flags_df.empty else pd.Series(dtype=int))

    base = employees_df.copy()
    if query:
        q = query.lower().strip()
        mask = (
            base[COL_NAME].astype(str).str.lower().str.contains(q, na=False)
            | base[COL_ID].astype(str).str.contains(q, na=False)
            | base[COL_ROLE].astype(str).str.lower().str.contains(q, na=False)
            | base[COL_DEPT].astype(str).str.lower().str.contains(q, na=False)
        )
        matches = base[mask].sort_values(COL_ANNUAL_SALARY, ascending=False)
    else:
        matches = base.sort_values(COL_ANNUAL_SALARY, ascending=False)

    total_matches = len(matches)
    shown = matches.head(50).copy()
    shown["Flags"] = shown[COL_ID].map(
        lambda eid: f"🔴 {int(flag_counts.get(eid, 0))}" if flag_counts.get(eid, 0) else "—"
    )
    shown["Salary"] = shown[COL_ANNUAL_SALARY].apply(fmt_money)
    display_cols = {
        COL_ID: "ID", COL_NAME: "Name", COL_ROLE: "Role", COL_LEVEL: "Level",
        COL_DEPT: "Department", "Salary": "Salary",
        "YearsAtCompany": "Tenure (yrs)", "Flags": "Flags",
    }
    table = shown[list(display_cols.keys())].rename(columns=display_cols).reset_index(drop=True)

    sel = st.dataframe(table, use_container_width=True, hide_index=True,
                       on_select="rerun", selection_mode="single-row", height=320)
    st.caption(f"Showing {len(table)} of {total_matches:,} matches. Click a row to view full profile.")

    sel_rows = sel.selection.rows if sel and sel.selection else []
    if sel_rows:
        st.session_state["lookup_selected_id"] = int(shown.iloc[sel_rows[0]][COL_ID])

    sel_id = st.session_state.get("lookup_selected_id")
    if sel_id is not None and sel_id in employees_df[COL_ID].values:
        emp = employees_df[employees_df[COL_ID] == sel_id].iloc[0]
        st.divider()
        st.markdown(f"## {emp[COL_NAME]}")
        st.caption(f"{emp[COL_ROLE]} L{emp[COL_LEVEL]} · {emp[COL_DEPT]} · Employee ID #{int(emp[COL_ID])}")

        cohort_df = employees_df[employees_df[COL_COHORT] == emp[COL_COHORT]]
        cohort_median = float(cohort_df[COL_ANNUAL_SALARY].median()) if len(cohort_df) else 0.0
        emp_salary = float(emp[COL_ANNUAL_SALARY])
        delta = emp_salary - cohort_median
        delta_pct = (delta / cohort_median * 100) if cohort_median else 0.0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Current salary", fmt_money(emp_salary))
        m2.metric("Vs cohort median", f"{'+' if delta >= 0 else '−'}{fmt_money(abs(delta))}",
                  f"{delta_pct:+.1f}%")
        m3.metric("Tenure", f"{int(emp['YearsAtCompany'])} yrs")
        m4.metric("Last hike", f"{int(emp['PercentSalaryHike'])}%")

        yac = int(emp["YearsAtCompany"])
        yir = int(emp["YearsInCurrentRole"])
        ysp = int(emp["YearsSinceLastPromotion"])
        hike = int(emp["PercentSalaryHike"])
        twy = int(emp["TotalWorkingYears"])
        ncw = int(emp["NumCompaniesWorked"])
        prior = max(0, twy - yac)
        joined = "**Joined this year**" if yac == 0 else f"Joined the company **{yac} year{'s' if yac != 1 else ''} ago**"
        role_switch = yac - yir
        if yir == 0:
            role_line = "Just moved into this role **this year**"
        elif role_switch <= 0:
            role_line = f"Has been in this role the entire **{yir} year{'s' if yir != 1 else ''}** of tenure"
        else:
            role_line = f"Current role for **{yir} years** (switched roles ~{role_switch} year{'s' if role_switch != 1 else ''} ago)"
        promo_line = "**Just promoted this year**" if ysp == 0 else f"Last promotion: **{ysp} year{'s' if ysp != 1 else ''} ago**"
        prior_line = (f"Prior industry experience: **{prior} years** across {ncw} companies"
                      if prior > 0 else f"No prior industry experience (worked at {ncw} companies total)")

        timeline_lines = [
            "### 📅 Career history",
            f"- {joined}",
            f"- {role_line}",
            f"- {promo_line}",
            f"- Last raise: **{hike}%**",
            f"- {prior_line}",
        ]
        if "YearsWithCurrManager" in emp.index:
            ywm = int(emp["YearsWithCurrManager"])
            timeline_lines.append(
                f"- Currently reports to manager for **{ywm} year{'s' if ywm != 1 else ''}**"
            )
        st.markdown("\n".join(timeline_lines))

        emp_flags = flags_df[flags_df["employee_id"] == sel_id] if not flags_df.empty else pd.DataFrame()
        st.markdown("### 🚩 Flags")
        if emp_flags.empty:
            st.success("✅ No compensation anomalies detected for this employee.")
        else:
            for _, fr in emp_flags.iterrows():
                msg = f"{fr['rule_icon']} **{fr['rule_label']}** — {fr['reason']}"
                sev = fr["severity"]
                if sev == SEVERITY_HIGH:
                    st.error(msg)
                elif sev == "Medium":
                    st.warning(msg)
                else:
                    st.info(msg)

        if len(cohort_df) >= 2:
            st.markdown("### 📊 Cohort comparison")
            cc1, cc2 = st.columns(2)
            with cc1:
                box = go.Figure()
                box.add_trace(go.Box(y=cohort_df[COL_ANNUAL_SALARY], name=str(emp[COL_COHORT]),
                                     marker_color="#4A9EFF", boxmean=True))
                box.add_trace(go.Scatter(x=[str(emp[COL_COHORT])], y=[emp_salary], mode="markers",
                                         marker=dict(symbol="diamond", color="#E74C3C", size=16),
                                         name=emp[COL_NAME]))
                box.update_layout(title=f"Cohort salary ({len(cohort_df)} employees)",
                                  height=320, showlegend=False, **DARK)
                st.plotly_chart(box, use_container_width=True)
            with cc2:
                hist = px.histogram(cohort_df, x=COL_ANNUAL_SALARY, nbins=20,
                                    title="Cohort histogram",
                                    color_discrete_sequence=["#4A9EFF"])
                hist.add_vline(x=emp_salary, line_color="#E74C3C", line_width=3,
                               annotation_text=emp[COL_NAME], annotation_position="top")
                hist.update_layout(height=320, bargap=0.05, **DARK)
                st.plotly_chart(hist, use_container_width=True)

        with st.expander("More details"):
            d1, d2 = st.columns(2)
            with d1:
                st.markdown("**Demographics & background**")
                st.markdown(
                    f"- Age: **{int(emp['Age'])}**\n"
                    f"- Gender: **{emp['Gender']}**\n"
                    f"- Marital status: **{emp['MaritalStatus']}**\n"
                    f"- Education level: {_rating_bar(emp['Education'], scale=5)}\n"
                    f"- Education field: **{emp['EducationField']}**\n"
                    f"- Distance from home: **{int(emp['DistanceFromHome'])} mi**\n"
                    f"- Business travel: **{emp['BusinessTravel']}**"
                )
            with d2:
                st.markdown("**Engagement & performance**")
                st.markdown(
                    f"- Performance rating: {_rating_bar(emp['PerformanceRating'], scale=4)}\n"
                    f"- Job satisfaction: {_rating_bar(emp['JobSatisfaction'], scale=4)}\n"
                    f"- Environment satisfaction: {_rating_bar(emp['EnvironmentSatisfaction'], scale=4)}\n"
                    f"- Work-life balance: {_rating_bar(emp['WorkLifeBalance'], scale=4)}\n"
                    f"- Overtime: **{emp['OverTime']}**\n"
                    f"- Stock option level: {_rating_bar(emp['StockOptionLevel'], scale=3)}\n"
                    f"- Attrition: **{emp['Attrition']}**"
                )


# ========== TAB 3: CHAT (Stream D) ==========

with tab_chat:
    import agent  # local module
    import demo_agent  # local demo (no API key)

    st.subheader("Ask PayGuard")

    use_llm = agent.chat_enabled()
    if not use_llm:
        st.caption(
            "🤖 Demo mode — running locally on your data. "
            "Set OPENAI_API_KEY in .env for full LLM chat."
        )

    st.session_state.setdefault("chat_history", [])

    SUGGESTIONS = [
        "Show me employees promoted without a raise",
        "Who are the top 3 most underpaid employees?",
        "Is there salary compression in any department?",
    ]
    s1, s2, s3 = st.columns(3)
    pending = st.session_state.pop("pending_prompt", None)
    for col, prompt in zip((s1, s2, s3), SUGGESTIONS):
        if col.button(prompt, key=f"suggest_{hash(prompt)}", use_container_width=True):
            pending = prompt

    for turn in st.session_state.chat_history:
        if turn.get("role") not in ("user", "assistant"):
            continue
        with st.chat_message(turn["role"]):
            st.markdown(turn.get("content", ""))

    typed = st.chat_input("Ask about a flag, an employee, or a cohort...")
    user_msg = typed or pending

    if user_msg:
        with st.chat_message("user"):
            st.markdown(user_msg)
        with st.chat_message("assistant"):
            with st.spinner("PayGuard is thinking..."):
                responder = agent.respond if use_llm else demo_agent.demo_respond
                reply, new_history = responder(
                    user_msg,
                    st.session_state.chat_history,
                    st.session_state["full_df"],
                    st.session_state["flagged_df"],
                    st.session_state["stats"],
                )
            st.markdown(reply)
        st.session_state.chat_history = new_history
        if pending and not typed:
            st.rerun()


# ========== TAB 4: RAW DATA ==========

with tab_raw:
    st.subheader("Raw employee data")
    query = st.text_input("Search by name or role", "", placeholder="e.g. Priya, Sales Executive")
    view = employees_df
    if query:
        q = query.lower()
        mask = (view[COL_NAME].astype(str).str.lower().str.contains(q)
                | view[COL_ROLE].astype(str).str.lower().str.contains(q))
        view = view[mask]
    st.caption(f"{len(view):,} rows")
    st.dataframe(view, use_container_width=True, hide_index=True, height=600)
