"""Visual helpers matching the PayGuard reference design."""
from __future__ import annotations

import html
import re

import streamlit as st

BG, SURFACE, SURFACE2 = "#0E1013", "#13161B", "#1D2128"
BORDER, TEXT, MUTED, FAINT = "#22262D", "#E8EAED", "#9AA1AC", "#8A919C"
SOFT, LINE, CARD = "#C9CDD3", "#2A2F37", "#171A20"
MINT = "#6FD3B5"
AMBER = "#E8BC5A"
SEV = {
    "High":   {"c": "#F08A76", "bg": "rgba(232,115,95,0.14)", "bar": "#E8735F"},
    "Medium": {"c": "#E8BC5A", "bg": "rgba(227,181,79,0.14)", "bar": "#E3B54F"},
    "Low":    {"c": "#A3B1CA", "bg": "rgba(147,164,192,0.14)", "bar": "#7F8DA6"},
}
SEV_ORDER = ["High", "Medium", "Low"]
RULE_SHORT = {"under": "Underpaid", "promo": "Promo / raise", "comp": "Compression", "over": "Above band"}
RULE_DESC = {
    "under": "below 88% of cohort median",
    "promo": "promoted, raise under 4%",
    "comp": "10+ yrs, below median",
    "over": "over 128% of median",
}
TONE = {"high": SEV["High"]["c"], "medium": SEV["Medium"]["c"], "muted": MUTED}
MASK = "$•••,•••"

esc = html.escape

# Fonts, colours, border colour and radius come from .streamlit/config.toml.
# This CSS only covers what the theme can't express.
CSS = f"""
<style>
/* the fixed top bar is transparent; let clicks reach the header actions underneath it */
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stHeader"], [data-testid="stHeader"] * {{ pointer-events: none !important; }}
[data-testid="stHeader"] button, [data-testid="stHeader"] a {{ pointer-events: auto !important; }}
[data-testid="stAppDeployButton"], [data-testid="stStatusWidget"], [data-testid="stDecoration"] {{ display: none; }}
.block-container {{ padding: 20px 32px 72px !important; max-width: 1360px; position: relative; }}
.stMain h1 {{ font-size: 24px !important; letter-spacing: -0.01em; padding: 0 !important; margin: 0 !important; line-height: 1.3 !important; }}
.stMain h2 {{ font-size: 18px !important; padding: 0 !important; margin: 0 !important; }}

/* sidebar */
section[data-testid="stSidebar"] {{ width: 248px !important; min-width: 248px !important; }}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding: 24px 18px !important; }}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {{ height: 0; padding: 0; }}

/* tabs: reference nav bar */
.stTabs [role="tablist"] {{ gap: 2px; border-bottom: 1px solid {BORDER}; }}
[data-testid="stTab"] {{ height: 56px; padding: 0 14px; color: {MUTED}; }}
[data-testid="stTab"] p {{ font-size: 14px; font-weight: 500; }}
[data-testid="stTab"][data-selected="true"] {{ color: {TEXT}; }}
[data-testid="stTab"] .react-aria-SelectionIndicator {{ background: {MINT}; height: 2px; }}
[data-testid="stTab"] code {{ font-family: 'IBM Plex Mono', monospace; font-size: 11px; padding: 1px 6px; border-radius: 999px; background: rgba(232,115,95,0.16); color: #F08A76; margin-left: 4px; }}
[data-testid="stTabPanel"] {{ padding-top: 28px; }}
[data-testid="stTabPanel"] > [data-testid="stVerticalBlock"] {{ gap: 28px; }}

/* header actions sit on the right end of the tab bar */
.st-key-hdr {{ position: absolute; right: 32px; top: 20px; z-index: 10; width: auto !important; height: 56px; }}

/* buttons */
.stButton button, .stDownloadButton button {{ min-height: 0; height: 36px; padding: 0 14px; }}
.stButton button p, .stDownloadButton button p {{ font-size: 13px; }}
.stButton button[kind="primary"] {{ color: {BG}; font-weight: 500; }}
.stDownloadButton button {{ height: 32px; background: {CARD}; }}
[class*="st-key-pager"] .stButton button {{ height: 30px; padding: 0 12px; }}
[class*="st-key-big"] .stButton button, [class*="st-key-big"] .stDownloadButton button {{ height: 38px; padding: 0 16px; background: transparent; }}
[class*="st-key-big"] .stButton button[kind="primary"] {{ background: {MINT}; }}
[class*="st-key-big"] .stButton button p, [class*="st-key-big"] .stDownloadButton button p {{ font-size: 14px; }}

/* filter chips (st.pills): selected chip is solid light, per the reference */
[data-testid="stButtonGroup"] button[data-variant="pills"] {{ min-height: 28px; height: 28px; padding: 0 10px; border-radius: 999px; background: transparent; border-color: {LINE}; color: {SOFT}; }}
[data-testid="stButtonGroup"] button[data-variant="pills"] * {{ font-size: 12.5px; }}
[data-testid="stButtonGroup"] button[data-variant="pills"][data-selected="true"] {{ background: {TEXT}; border-color: {TEXT}; color: {BG}; }}
.st-key-r_cols [data-testid="stButtonGroup"] button[data-variant="pills"] {{ height: 26px; min-height: 26px; padding: 0 9px; border-radius: 6px; border-color: {BORDER}; color: #6F7682; }}
.st-key-r_cols [data-testid="stButtonGroup"] button[data-variant="pills"] * {{ font-family: 'IBM Plex Mono', monospace; font-size: 12px; }}
.st-key-r_cols [data-testid="stButtonGroup"] button[data-variant="pills"][data-selected="true"] {{ background: {SURFACE2}; border-color: #3A414C; color: {TEXT}; }}
.pg-vr {{ width: 1px; height: 18px; background: {LINE}; }}

/* cards (bordered containers) */
[class*="st-key-card"] {{ border-radius: 12px; padding: 20px; background: {SURFACE}; }}
section[data-testid="stSidebar"] [class*="st-key-card"] {{ border-radius: 10px; padding: 14px; background: {CARD}; }}
.st-key-card_empty {{ max-width: 720px; border: 1px dashed {LINE} !important; background: transparent; border-radius: 14px; padding: 48px 40px; }}
.st-key-card_error {{ max-width: 720px; border-color: rgba(232,115,95,0.35) !important; background: rgba(232,115,95,0.05); border-radius: 14px; padding: 32px; }}
.st-key-card_loading {{ max-width: 560px; border-radius: 14px; padding: 32px; }}

/* file uploaders shown as plain buttons (the dataset card already shows the file name) */
[data-testid="stFileUploader"] > label {{ display: none; }}
[data-testid="stFileUploaderDropzone"] {{ padding: 0; background: transparent; border: none; min-height: 0; display: block; }}
[data-testid="stFileUploaderDropzone"] > :not(span):not(input) {{ display: none !important; }}
[data-testid="stFileUploaderDropzone"] button {{ height: 38px; min-width: 130px; padding: 0 16px; border: 1px solid {LINE}; background: transparent; }}
[data-testid="stFileUploaderDropzone"] button > * {{ display: none; }}
[data-testid="stFileUploaderDropzone"] button::after {{ color: {TEXT}; font-size: 14px; }}
.st-key-upload [data-testid="stFileUploaderDropzone"] button::after {{ content: "Upload CSV"; }}
.st-key-upload_alt [data-testid="stFileUploaderDropzone"] button {{ background: {MINT}; border-color: {MINT}; min-width: 170px; }}
.st-key-upload_alt [data-testid="stFileUploaderDropzone"] button::after {{ content: "Choose another file"; color: {BG}; font-weight: 500; }}
.st-key-upload_side [data-testid="stFileUploaderDropzone"] button {{ width: 100%; height: 34px; }}
.st-key-upload_side [data-testid="stFileUploaderDropzone"] button::after {{ content: "Load another file"; font-size: 13px; }}

/* chat input: mint send button, per the reference */
.st-key-chat_in [data-testid="stChatInputSubmitButton"]:not(:disabled) {{ background: {MINT}; color: {BG}; }}

/* profile drawer */
[data-testid="stDialog"] [role="dialog"] {{ background: {SURFACE}; }}
[data-testid="stDialog"] h2 {{ font-size: 20px !important; }}

/* HTML blocks */
.pg-card {{ border: 1px solid {BORDER}; border-radius: 12px; padding: 20px; background: {SURFACE}; height: 100%; display: flex; flex-direction: column; gap: 6px; min-width: 0; }}
.pg-label {{ font-size: 13px; color: {MUTED}; }}
.pg-value {{ font-size: 28px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }}
.pg-sub {{ font-size: 12.5px; color: {MUTED}; }}
.pg-mono {{ font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: {FAINT}; }}
.pg-chip {{ display:inline-block; font-size:11.5px; padding:2px 7px; border-radius:5px; white-space:nowrap; }}
.pg-note {{ display:flex; gap:10px; align-items:flex-start; font-size:12.5px; line-height:1.55; color:{MUTED}; padding:10px 14px; border-radius:8px; background:{SURFACE}; border:1px solid {SURFACE2}; }}
.pg-warn {{ font-size:12.5px; line-height:1.5; padding:10px 12px; border-radius:8px; background:rgba(227,181,79,0.08); border:1px solid rgba(227,181,79,0.25); color:#E8D3A0; }}
.pg-kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; }}
.pg-kpis .wide {{ grid-column: span 2; }}
.pg-sub-h {{ font-size:13px; color:{MUTED}; margin-top:4px; }}
.pg-dept {{ width:100%; border-collapse:collapse; font-size:13.5px; font-variant-numeric:tabular-nums; }}
.pg-dept th {{ text-align:right; font-weight:500; font-size:12px; color:{MUTED}; padding:8px; border-bottom:1px solid {BORDER}; white-space:nowrap; }}
.pg-dept td {{ padding:12px 8px; text-align:right; border-bottom:1px solid {SURFACE2}; }}
.pg-dept th:first-child, .pg-dept td:first-child {{ text-align:left; padding-left:0; }}
.pg-dept th:last-child, .pg-dept td:last-child {{ padding-right:0; }}
.pg-raw {{ border:1px solid {BORDER}; border-radius:12px; overflow-x:auto; background:{SURFACE}; }}
.pg-raw table {{ width:100%; border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums; }}
.pg-raw th {{ font-weight:500; font-size:12px; color:{MUTED}; padding:12px 14px; border-bottom:1px solid {BORDER}; white-space:nowrap; }}
.pg-raw td {{ padding:10px 14px; border-bottom:1px solid {SURFACE2}; white-space:nowrap; }}
.pg-raw tr:last-child td {{ border-bottom:none; }}
.pg-raw tr:hover td {{ background:{CARD}; }}
.pg-empty {{ padding:40px; text-align:center; font-size:14px; color:{SOFT}; }}
.pg-legend {{ display:flex; gap:12px; font-size:12px; color:{MUTED}; }}
.pg-legend span {{ display:flex; align-items:center; gap:6px; }}
.pg-legend i {{ width:8px; height:8px; border-radius:2px; display:inline-block; }}
.pg-meta {{ font-size:12px; color:{MUTED}; line-height:1.55; white-space:pre-line; }}
.pg-facts {{ display:grid; grid-template-columns:1fr 1fr; gap:1px; background:{BORDER}; border:1px solid {BORDER}; border-radius:10px; overflow:hidden; }}
.pg-facts div {{ background:{SURFACE}; padding:12px 14px; display:flex; flex-direction:column; gap:2px; }}
.pg-flag {{ border:1px solid {BORDER}; border-radius:10px; padding:14px; display:flex; flex-direction:column; gap:8px; margin-top:10px; }}
.pg-caption {{ font-size:12.5px; color:{MUTED}; }}
</style>
"""


def inject():
    st.html(CSS)


def md(markup: str, width="stretch"):
    st.html(markup, width=width)


def money(v, masked: bool = False) -> str:
    if v is None or v != v:
        return "—"
    if masked:
        return MASK
    s = f"${abs(round(v)):,}"
    return f"−{s}" if v < 0 else s


def pct(ratio) -> str:
    """Signed % difference from the median, e.g. 0.76 -> '−24%'."""
    p = round((ratio - 1) * 100)
    return f"−{abs(p)}%" if p < 0 else f"+{p}%" if p > 0 else "0%"


def mask_text(s: str, masked: bool) -> str:
    return re.sub(r"\$[\d,]+(?:\.\d+)?", MASK, s) if masked else s


def chip(label: str, sev: str | None = None) -> str:
    if sev is None:
        return f'<span class="chip" style="background:{SURFACE2};color:{FAINT}">{esc(label)}</span>'
    return f'<span class="chip" style="background:{SEV[sev]["bg"]};color:{SEV[sev]["c"]}">{esc(label)}</span>'


def chips(rules_with_sev: list[tuple[str, str]]) -> str:
    return '<div class="chips">' + "".join(chip(RULE_SHORT[r], s) for r, s in rules_with_sev) + "</div>"


def kpi(label: str, value: str, sub: str = "", color: str = TEXT, big: bool = False) -> str:
    return (f'<div class="pg-card{" wide" if big else ""}"><div class="pg-label">{esc(label)}</div>'
            f'<div class="pg-value" style="font-size:{"40px" if big else "28px"};color:{color}">{esc(value)}</div>'
            f'<div class="pg-sub">{esc(sub)}</div></div>')


def note(text: str) -> str:
    return (f'<div class="pg-note"><span style="color:{AMBER};font-family:\'IBM Plex Mono\',monospace">i</span>'
            f'<span>{esc(text)}</span></div>')


def legend() -> str:
    return '<div class="pg-legend">' + "".join(
        f'<span><i style="background:{SEV[s]["bar"]}"></i>{s}</span>' for s in SEV_ORDER) + "</div>"


def banner(kind: str, title: str, text: str):
    dot, bg, border = {
        "demo": ("#E3B54F", "rgba(227,181,79,0.07)", "rgba(227,181,79,0.25)"),
        "connected": (MINT, "rgba(111,211,181,0.06)", "rgba(111,211,181,0.22)"),
        "offline": ("#E8735F", "rgba(232,115,95,0.07)", "rgba(232,115,95,0.3)"),
    }[kind]
    md(f'<div style="display:flex;gap:10px;padding:12px 14px;border-radius:9px;font-size:13px;line-height:1.55;'
       f'background:{bg};border:1px solid {border}"><span style="width:7px;height:7px;border-radius:50%;margin-top:7px;'
       f'flex-shrink:0;background:{dot}"></span><div><b style="font-weight:500">{esc(title)}</b> '
       f'<span style="color:{SOFT}">{esc(text)}</span></div></div>')


def status_card(label: str, title: str, meta: str, dot: str, note: str = "") -> str:
    note_html = f'<div style="font-size:12px;color:{AMBER};line-height:1.45;white-space:pre-line">{esc(note)}</div>' if note else ""
    return (f'<div style="display:flex;flex-direction:column;gap:10px"><div class="pg-mono">{esc(label)}</div>'
            f'<div style="display:flex;gap:8px;align-items:flex-start"><span style="width:7px;height:7px;'
            f'border-radius:50%;margin-top:6px;flex-shrink:0;background:{dot}"></span><span style="font-size:13px;font-weight:500;'
            f'word-break:break-all;line-height:1.4">{esc(title)}</span></div><div class="pg-meta">{esc(meta)}</div>{note_html}</div>')


def cohort_band(salary, cmin, p25, med, p75, cmax, dot_color: str, label: str, masked: bool = False) -> str:
    span = (cmax - cmin) or 1
    pos = lambda v: max(0, min(100, (v - cmin) / span * 100))
    return (
        f'<div style="border:1px solid {BORDER};border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:10px">'
        f'<div style="font-size:13px;font-weight:500">Position in cohort <span style="color:{FAINT};font-weight:400">· {esc(label)}</span></div>'
        f'<div style="position:relative;height:28px">'
        f'<div style="position:absolute;left:0;right:0;top:12px;height:4px;background:#262B33;border-radius:2px"></div>'
        f'<div style="position:absolute;top:8px;height:12px;border-radius:3px;background:rgba(111,211,181,0.22);left:{pos(p25)}%;width:{pos(p75) - pos(p25)}%"></div>'
        f'<div style="position:absolute;top:5px;width:2px;height:18px;background:{MUTED};left:{pos(med)}%"></div>'
        f'<div style="position:absolute;top:7px;width:14px;height:14px;border-radius:50%;transform:translateX(-50%);border:2px solid {BG};left:{pos(salary)}%;background:{dot_color}"></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;font-size:11.5px;color:{FAINT};font-variant-numeric:tabular-nums">'
        f'<span>Min {money(cmin, masked)}</span><span>Median {money(med, masked)}</span><span>Max {money(cmax, masked)}</span></div>'
        f'<div style="font-size:11.5px;color:{FAINT}">Shaded area is the middle 50% (p25–p75).</div></div>')
