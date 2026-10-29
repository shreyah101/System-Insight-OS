"""Database-only dashboard; this module never creates a monitoring collector."""
import json
import os
import sqlite3

import streamlit as st

from src.config import load_config
from src.storage import Repository
from src.display_time import format_time
from src.ui import CSS, PAGES

st.set_page_config(page_title="System Insight OS", page_icon="▥", layout="wide")
st.html(CSS)


@st.cache_resource
def resources():
    config = load_config(os.environ.get("SYSTEM_INSIGHT_CONFIG"))
    repository = Repository(config.db_path)
    repository.initialize()
    return config, repository


try:
    cfg, repo = resources()
except (ValueError, OSError, sqlite3.Error) as exc:
    st.error(f"Cannot initialize System Insight OS: {exc}")
    st.stop()

with st.sidebar:
    st.html('<div class="brand">SYSTEM INSIGHT OS</div>')
    st.caption("AI-Based System Health Monitoring Engine")
    page = st.radio("Workspace", list(PAGES), label_visibility="collapsed")
    st.divider()
    sessions = repo.sessions()
    choice = st.selectbox("Recorded session", ["Latest live session"] + [s["id"] for s in sessions],
                          format_func=lambda v: v if v == "Latest live session" else next(format_time(s["started_at"]) + " · " + s["status"] + " · " + s["id"][:6] for s in sessions if s["id"] == v))
    st.caption("Start collector in a terminal:")
    st.code("python -m scripts.run_monitor", language="bash")
    st.caption("Local only · No external APIs\n\nRefreshes read SQLite. One worker owns collection.")


@st.fragment(run_every=cfg.ui_refresh_seconds)
def render():
    try:
        session = repo.session(None if choice == "Latest live session" else choice)
        # Historical bands and model explanations must use the settings recorded with the session.
        from src.config import Config
        session_cfg = Config(**json.loads(session["config_json"])) if session else cfg
        st.session_state["chart_threshold"] = session_cfg.zscore_threshold
        PAGES[page](repo, session, session_cfg)
    except (sqlite3.Error, OSError) as exc:
        st.error(f"Cannot read monitoring data: {exc}. The dashboard will retry on its next refresh.")


render()
