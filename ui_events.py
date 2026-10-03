"""Clickable HTML blocks, built on st.components.v2.

The component renders trusted, server-built HTML (all user data is escaped with
html.escape before it gets here) and reports clicks on elements carrying
`data-act`/`data-val` attributes back to Python as one-shot trigger values.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

_DIR = Path(__file__).parent / "components"
_component = st.components.v2.component(
    "payguard_html",
    css=(_DIR / "payguard.css").read_text(),
    js=(_DIR / "payguard.js").read_text(),
)


def html_block(html: str, key: str) -> dict | None:
    """Render `html`; return {act, val} on the run right after a click, else None."""
    result = _component(data={"html": html}, key=key, on_event_change=lambda: None)
    return result.event
