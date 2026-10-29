from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import Config
from src.display_time import chart_time, format_time, localize_timestamps
from src.evaluation import SCENARIOS, evaluate_local, replay
from src.models import LABELS, METRICS, UNITS, utc_now
from src.runtime import json_decision, monitor_status
from src.storage import Repository
from src.telemetry import top_processes
from src.workloads import KINDS, launch, limits

COLORS = {"NORMAL": "#38c9c0", "LOW": "#9dcf7b", "MEDIUM": "#e7b85c", "HIGH": "#f29361", "CRITICAL": "#ef6b78"}
CSS = """
<style>
.block-container {max-width:1600px;padding-top:4.5rem;padding-bottom:2rem}
[data-testid="stSidebar"] {border-right:1px solid #253246}
[data-testid="stMetric"] {padding:.3rem 0}
[data-testid="stMetricLabel"] {color:#a6b5c8;font-size:.78rem;letter-spacing:.04em}
[data-testid="stMetricValue"] {font-size:1.3rem;font-variant-numeric:tabular-nums;font-weight:600}
.st-key-metric_cards [data-testid="stCaptionContainer"] {min-height:3rem}
[data-testid="stVerticalBlockBorderWrapper"]>div {border-radius:8px}
h1 {font-size:1.8rem!important;letter-spacing:-.04em;font-weight:700!important}
h2 {font-size:1.2rem!important;letter-spacing:-.015em}
h3 {font-size:1rem!important}
[data-testid="stCaptionContainer"] {color:#99aac0}
hr {margin:.8rem 0;border-color:#253246}
[data-testid="stProgressBar"]>div>div>div>div {background:#38c9c0}
.brand {color:#38c9c0;font-size:.7rem;font-weight:700;letter-spacing:.18em;margin-bottom:.45rem}
@media (max-width:1100px) {
 .st-key-metric_cards [data-testid="stHorizontalBlock"] {flex-wrap:wrap}
 .st-key-metric_cards [data-testid="stColumn"] {flex:1 1 calc(33.333% - 1rem);min-width:140px}
}
</style>
"""


def format_value(value, metric: str) -> str:
    if value is None or pd.isna(value):
        return "Unavailable"
    if metric.endswith("bps"):
        for size, unit in ((2**30, "GiB/s"), (2**20, "MiB/s"), (2**10, "KiB/s")):
            if value >= size:
                return f"{value / size:.1f} {unit}"
        return f"{value:.0f} B/s"
    if metric == "process_count":
        return f"{value:,.0f}"
    return f"{value:.1f}%"


def figure_style(fig: go.Figure, height: int = 310, unit: str = "") -> go.Figure:
    fig.update_layout(template="plotly_dark", height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10, r=10, t=20, b=10), font=dict(color="#aebdd0", size=12),
                      legend=dict(orientation="h", y=1.14, x=0), hovermode="x unified",
                      xaxis=dict(title="Time (IST)", gridcolor="#202d40"), yaxis=dict(title=unit, gridcolor="#202d40"))
    return fig


def metric_chart(rows: list[dict], metrics: list[str], baseline: bool = False) -> go.Figure:
    fig = go.Figure()
    x = [chart_time(r["timestamp"]) for r in rows]
    colors = ["#38c9c0", "#80acfa", "#e7b85c"]
    for index, metric in enumerate(metrics):
        color = colors[index % len(colors)]
        if baseline:
            stats = [json_decision(r)["baseline"].get(metric) for r in rows]
            # Configured threshold and effective sigma are saved with every decision's baseline.
            threshold = st.session_state.get("chart_threshold", 3.)
            means = [s["mean"] if s else None for s in stats]
            upper = [s["mean"] + threshold * s["effective_std"] if s else None for s in stats]
            lower = [max(0, s["mean"] - threshold * s["effective_std"]) if s else None for s in stats]
            fig.add_trace(go.Scatter(x=x, y=upper, mode="lines", line=dict(width=0), name="Upper statistical bound", showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=x, y=lower, mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(56,201,192,.10)", name="Expected statistical band", hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=x, y=means, mode="lines", line=dict(color="#8195af", width=1, dash="dot"), name="Previous-window mean"))
        fig.add_trace(go.Scatter(x=x, y=[r.get(metric) for r in rows], mode="lines", name=LABELS[metric], line=dict(color=color, width=2), connectgaps=False))
        if len(metrics) == 1:
            flagged = [r for r in rows if r["ready"] and r["severity"] != "NORMAL" and r.get(metric) is not None]
            fig.add_trace(go.Scatter(x=[chart_time(r["timestamp"]) for r in flagged], y=[r[metric] for r in flagged], mode="markers", name="Detector flag (any resource)",
                                     marker=dict(size=7, color=[COLORS[r["severity"]] for r in flagged]), text=[r["severity"] for r in flagged]))
    return figure_style(fig, unit=UNITS[metrics[0]])


def empty():
    st.info("No telemetry recorded for this session. Start the collector in a terminal: python -m scripts.run_monitor")


def header(repo: Repository, session: dict | None, cfg: Config, title: str):
    latest_rows = repo.metrics(session["id"], limit=1) if session else []
    latest = latest_rows[-1] if latest_rows else None
    metadata = json.loads(session["metadata_json"]) if session else {}
    status = monitor_status(session, latest, cfg)
    left, right = st.columns([4, 1])
    with left:
        st.html('<div class="brand">SYSTEM INSIGHT OS / LOCAL OBSERVABILITY</div>')
        st.title(title)
        st.caption(f"{metadata.get('hostname', 'Local machine')}  ·  {metadata.get('os', 'OS available after collector starts')}  ·  All times IST (UTC+05:30)")
    with right:
        st.badge(status, color="green" if status == "Healthy" else "orange" if status in ("Warming up", "Initializing") else "red" if status in ("Anomaly detected", "Collector error", "Stale data") else "gray")
        st.caption(f"Last sample: {format_time(latest['timestamp'], time_only=True)}" if latest else "Awaiting first sample")
    if status in ("Offline", "Stale data", "Collector error"):
        st.warning({"Offline": "Collector is offline. Saved readings remain available; they are historical.", "Stale data": "Collector heartbeat is stale. Readings below are historical until sampling resumes.", "Collector error": f"Collector reported an error: {(session or {}).get('error')}"}[status])
    st.divider()
    return latest, status


def evidence_table(payload: dict) -> pd.DataFrame:
    return pd.DataFrame([{"Resource": LABELS[k], "Z-Score": round(payload["zscore"]["scores"][k], 2) if k in payload["zscore"]["scores"] else None,
                          "Observed": format_value(payload["sample"]["values"].get(k), k),
                          "Baseline": format_value(s["mean"], k), "Std deviation": round(s["std"], 3),
                          "Effective std": round(s["effective_std"], 3)}
                         for k, s in payload["baseline"].items()])


def readiness(payload: dict, cfg: Config):
    if not payload["ready"]:
        count = payload["warmup_count"]
        st.progress(min(count / cfg.rolling_window_size, 1), text=f"Historical baseline: {count}/{cfg.rolling_window_size} valid samples before this reading")
        st.caption("Live readings remain visible. Alerts are paused until the window and supported inputs are valid. Feature changes restart warm-up.")
    else:
        st.caption(f"DETECTORS READY  ·  {cfg.rolling_window_size} historical readings  ·  {len(payload['features'])}/6 supported inputs  ·  Prior samples only")


def overview(repo: Repository, session: dict | None, cfg: Config):
    latest, status = header(repo, session, cfg, "Intelligent System Health Monitoring")
    if not latest:
        empty()
        return
    payload = json_decision(latest)
    readiness(payload, cfg)
    with st.container(key="metric_cards"):
        columns = st.columns(6)
        for col, metric in zip(columns, METRICS):
            with col.container(border=True):
                stat = payload["baseline"].get(metric)
                value = latest[metric]
                difference = value - stat['mean'] if stat and value is not None else None
                delta = f"{'+' if difference >= 0 else '-'}{format_value(abs(difference), metric)} vs mean" if difference is not None else None
                st.metric(LABELS[metric], format_value(value, metric))
                st.caption(delta or payload["sample"]["quality"].get(metric, "Baseline pending"))
    rows = repo.metrics(session["id"], limit=150)
    left, right = st.columns([2.3, 1])
    with left.container(border=True):
        st.subheader("Processor & physical memory")
        st.caption("Most recent 150 readings · Genuine host telemetry")
        st.plotly_chart(metric_chart(rows, ["cpu_percent", "ram_percent"]), width="stretch", key="overview_performance")
    with right.container(border=True):
        st.subheader("Current detector decision")
        st.markdown(f"### {latest['severity'] if payload['ready'] else 'Learning baseline'}")
        st.write(payload["explanation"])
        st.caption("Severity indicates investigation priority. It does not predict a crash.")
        st.divider()
        uptime = payload["timing"].get("monitor_uptime_seconds", 0)
        st.caption(f"Recorded monitor uptime: {timedelta(seconds=int(uptime))}")
        st.caption(f"Z-Score: {'ready' if payload['ready'] else 'waiting'} · Forest: {'ready' if payload['forest']['ready'] else 'waiting'}")
        st.caption(f"Collector RAM: {payload['timing'].get('monitor_ram_mib', 0):.1f} MiB · Detection: {payload['timing'].get('detection_ms', 0):.1f} ms")
    left, right = st.columns([1.3, 1])
    with left.container(border=True):
        st.subheader("Storage activity")
        st.plotly_chart(metric_chart(rows, ["disk_read_bps", "disk_write_bps"]), width="stretch", key="overview_disk")
    with right.container(border=True):
        st.subheader("Recent alert episodes")
        alerts = repo.alerts(session["id"], limit=5)
        if alerts:
            st.dataframe(pd.DataFrame(localize_timestamps(alerts))[["first_seen", "severity", "status", "occurrence_count"]], hide_index=True, width="stretch")
            st.caption("Open Alert history to inspect baseline evidence and episode recovery.")
        else:
            st.caption("No alert episodes recorded for this session.")
        counts = repo.summary(session["id"])
        st.caption(f"{counts['samples']:,} stored samples · {sum(counts['episodes'].values())} episodes")


def resources(repo, session, cfg):
    latest, _ = header(repo, session, cfg, "Resource explorer")
    if not latest:
        empty()
        return
    c1, c2 = st.columns([1, 2])
    metric = c1.selectbox("Resource", METRICS, format_func=lambda k: LABELS[k])
    span = c2.selectbox("Time range", ["Last 5 minutes", "Last 15 minutes", "Last 30 minutes", "Last hour", "Entire available session"])
    minutes = {"Last 5 minutes": 5, "Last 15 minutes": 15, "Last 30 minutes": 30, "Last hour": 60}.get(span)
    start = (datetime.fromisoformat(latest["timestamp"]) - timedelta(minutes=minutes)).isoformat() if minutes else None
    rows = repo.metrics(session["id"], start=start, limit=10000)
    st.caption("Ranges end at the last saved reading. At most 10,000 recent points are plotted; full sessions can be exported.")
    values = pd.Series([r.get(metric) for r in rows], dtype=float).dropna()
    if values.empty:
        st.info(f"{LABELS[metric]} is unavailable on this host or in this interval.")
        return
    for col, label, value in zip(st.columns(4), ["Minimum", "Maximum", "Mean", "Most recent"], [values.min(), values.max(), values.mean(), rows[-1].get(metric)]):
        col.metric(label, format_value(value, metric))
    st.plotly_chart(metric_chart(rows, [metric], baseline=True), width="stretch", key="resource_detail")
    metric_flags = sum(metric in json_decision(r)["zscore"]["flagged"] for r in rows)
    st.caption(f"{metric_flags} statistical flags for this resource. Shaded band = prior-window mean ± {cfg.zscore_threshold:g} × effective standard deviation. Markers show any detector flag, which may concern other resources.")
    with st.expander("Data quality and units"):
        st.write(latest and json_decision(latest)["sample"]["quality"])
        st.caption("Disk activity is bytes per second, not disk capacity or percent busy. Process count includes all existing processes returned by the OS.")


def anomalies(repo, session, cfg):
    latest, _ = header(repo, session, cfg, "Anomaly detection")
    if not latest:
        empty()
        return
    payload = json_decision(latest)
    readiness(payload, cfg)
    left, right = st.columns(2)
    with left.container(border=True):
        st.subheader("01 / Z-Score")
        st.write(f"Each input is compared with its previous {cfg.rolling_window_size} readings. An absolute Z-Score strictly above {cfg.zscore_threshold:g} flags a deviation.")
        st.metric("Largest absolute Z", f"{max((abs(z) for z in payload['zscore']['scores'].values()), default=0):.2f}" if payload["ready"] else "Waiting")
        st.dataframe(evidence_table(payload), hide_index=True, width="stretch")
        st.caption("Effective std is the larger of measured population std and the configured unit-specific floor. Negative Z means below baseline.")
    with right.container(border=True):
        st.subheader("02 / Isolation Forest")
        forest = payload["forest"]
        st.metric("Decision score", f"{forest['score']:.4f}" if forest["score"] is not None else "Waiting")
        st.write("Random splits isolate unusual combinations of resources. A negative decision score indicates an outlier; this is not a probability of failure.")
        st.caption(f"Latest result: {'Outlier' if forest['anomaly'] else 'Inlier' if forest['ready'] else 'Not evaluated'}")
        st.caption(f"Last fit: {format_time(forest['trained_at']) if forest['trained_at'] else 'Pending'}")
        st.caption(f"Training rows: {forest['training_samples']} · Trees: {cfg.isolation_forest_estimators} · Seed: {cfg.random_seed}")
        st.write("Features: " + (", ".join(LABELS[k] for k in payload["features"]) or "Waiting"))
        st.caption(f"Retraining considered every {cfg.retraining_interval_samples} eligible readings, postponed during incidents and until {cfg.recovery_samples_before_retraining} consecutive clean readings.")
    with st.container(border=True):
        st.subheader("Combined decision")
        st.write(payload["explanation"])
        st.dataframe(pd.DataFrame([
            {"Priority": "NORMAL", "Rule": "Neither detector flags"},
            {"Priority": "LOW", "Rule": f"Z-Score only; {cfg.zscore_threshold:g} < |Z|max ≤ {cfg.zscore_medium_threshold:g}"},
            {"Priority": "MEDIUM", "Rule": f"Z-Score only; |Z|max > {cfg.zscore_medium_threshold:g}"},
            {"Priority": "HIGH", "Rule": "Isolation Forest only"},
            {"Priority": "CRITICAL", "Rule": "Both detectors flag the same reading"}]), hide_index=True, width="stretch")
    table = evidence_table(payload)
    if payload["zscore"]["scores"]:
        scores = payload["zscore"]["scores"]
        fig = go.Figure(go.Bar(x=[LABELS[k] for k in scores], y=list(scores.values()), marker_color=["#ef6b78" if abs(z) > cfg.zscore_threshold else "#38c9c0" for z in scores.values()]))
        fig.add_hline(y=cfg.zscore_threshold, line_dash="dot", line_color="#e7b85c")
        fig.add_hline(y=-cfg.zscore_threshold, line_dash="dot", line_color="#e7b85c")
        fig = figure_style(fig, unit="Signed Z-Score")
        fig.update_xaxes(title="Resource")
        st.plotly_chart(fig, width="stretch", key="signed_z")


def csv_rows(rows: list[dict]) -> str:
    output = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(localize_timestamps(rows))
    return output.getvalue()


def history(repo, session, cfg):
    header(repo, session, cfg, "Alert history")
    if not session:
        empty()
        return
    counts = repo.summary(session["id"])
    episodes = counts["episodes"]
    for col, title, value in zip(st.columns(3), ["Total episodes", "Active episodes", "Resolved episodes"], [sum(episodes.values()), episodes.get("Active", 0), episodes.get("Resolved", 0)]):
        col.metric(title, value)
    st.caption("Episodes left active when a collector stops remain unresolved; a restart cannot prove recovery.")
    c1, c2, c3, c4 = st.columns(4)
    severity = c1.selectbox("Severity", ["All", "LOW", "MEDIUM", "HIGH", "CRITICAL"])
    detector = c2.selectbox("Detector", ["Both / either", "Z-Score", "Isolation Forest"])
    period = c3.selectbox("Episode start time", ["Entire session", "Last hour", "Last 24 hours"])
    search = c4.text_input("Search explanation")
    ref = datetime.fromisoformat(session["heartbeat"])
    since = (ref - timedelta(hours=1 if period == "Last hour" else 24)).isoformat() if period != "Entire session" else None
    records = repo.alerts(session["id"], severity=None if severity == "All" else severity,
                          detector={"Z-Score": "zscore", "Isolation Forest": "forest"}.get(detector), start=since)
    records = [r for r in records if search.lower() in r["explanation"].lower()]
    st.caption("Showing up to 500 recent matching episodes. Filters use episode start time; summary counts cover the selected session.")
    if not records:
        st.info("No alert episodes match these filters.")
    else:
        df = pd.DataFrame(records)
        st.dataframe(pd.DataFrame(localize_timestamps(records))[["id", "first_seen", "last_seen", "severity", "status", "occurrence_count", "explanation"]], hide_index=True, width="stretch")
        st.download_button("Export filtered alerts (CSV)", csv_rows(records), "alert_episodes.csv", "text/csv")
        choice = st.selectbox("Inspect episode", [r["id"] for r in records])
        record = next(r for r in records if r["id"] == choice)
        with st.container(border=True):
            st.subheader(f"Episode {choice} / {record['severity']} / {record['status']}")
            st.write(record["explanation"])
            st.caption(f"First: {format_time(record['first_seen'])} · Latest detection: {format_time(record['last_seen'])} · Occurrences: {record['occurrence_count']}")
            st.caption(f"Peak priority: {record['severity']} · Detector flags are the union across the episode; evidence below is the latest detection.")
            st.write("Affected resources: " + ", ".join(LABELS[k] for k in json.loads(record["affected_json"])))
            st.caption("For forest-only detections, these are the model inputs; the forest does not identify individual causal resources.")
            st.dataframe(evidence_table(json.loads(record["evidence_json"])), hide_index=True, width="stretch")
            st.caption(f"Resolved at: {format_time(record['resolved_at']) if record['resolved_at'] else 'Recovery not established'}")
            with st.expander("Full recorded detector evidence"):
                st.json(localize_timestamps(json.loads(record["evidence_json"])))
        left, right = st.columns(2)
        with left:
            data = pd.Series([r["severity"] for r in records]).value_counts()
            fig = go.Figure(go.Bar(x=data.index.tolist(), y=data.tolist(), marker_color=[COLORS[k] for k in data.index]))
            fig = figure_style(fig, height=240, unit="Episodes")
            fig.update_xaxes(title="Severity")
            st.plotly_chart(fig, width="stretch", key="severity_breakdown")
        with right:
            dates = pd.to_datetime([chart_time(r["first_seen"]) for r in records]).floor("min").value_counts().sort_index()
            st.plotly_chart(figure_style(go.Figure(go.Bar(x=dates.index, y=dates.values, marker_color="#38c9c0")), height=240, unit="Episodes / minute"), width="stretch", key="episode_frequency")
    with st.expander("Session telemetry export"):
        st.caption("Includes raw values, per-sample decisions, baselines, quality and model scores.")
        if st.button("Prepare full telemetry CSV"):
            original = list(csv.DictReader(io.StringIO(repo.export_metrics(session["id"]))))
            st.session_state["export_csv_ist"] = (session["id"], csv_rows(original))
        export = st.session_state.get("export_csv_ist")
        if export and export[0] == session["id"]:
            st.download_button("Download telemetry CSV", export[1], f"telemetry_{session['id'][:8]}.csv", "text/csv")


def evaluation(repo, session, cfg):
    latest, status = header(repo, session, cfg, "Evaluation & demo lab")
    st.caption("Live workloads change the local host. Synthetic replay uses a separate in-memory detector and never writes to live history.")
    synthetic, workload, local = st.tabs(["Synthetic replay", "Bounded local workloads", "Recorded session evaluation"])
    with synthetic:
        st.subheader("Reproducible anomaly replay / SIMULATED")
        name = st.selectbox("Simulated scenario", SCENARIOS)
        c1, c2 = st.columns([1, 4])
        if c1.button("Run replay", type="primary"):
            with st.spinner("Scoring synthetic readings through both real detectors…"):
                st.session_state["simulation"] = replay(name, cfg)
        if c2.button("Reset simulation"):
            st.session_state.pop("simulation", None)
        simulation = st.session_state.get("simulation")
        if simulation:
            rows, report = simulation
            st.caption(f"SIMULATED · {report['scenario']} · Seed {report['seed']} · {report['eligible_samples']} scored readings; warm-up excluded")
            metric = st.selectbox("Replay resource", METRICS, format_func=lambda k: LABELS[k])
            st.plotly_chart(metric_chart(rows, [metric], baseline=True), width="stretch", key="simulation_chart")
            st.dataframe(pd.DataFrame({k: report[k] for k in ("zscore", "isolation_forest", "combined")}).T, width="stretch")
            st.caption("Labels indicate injected synthetic workload changes. Precision and recall describe this scenario, not real-world failure detection accuracy.")
            st.json(localize_timestamps({k: v for k, v in report.items() if k not in ("zscore", "isolation_forest", "combined")}))
            st.download_button("Download simulation report", json.dumps(localize_timestamps(report), indent=2), "synthetic_evaluation.json", "application/json")
        else:
            st.info("Select a scenario and run replay. No synthetic results have been generated in this browser session.")
    with workload:
        st.subheader("Short, explicitly started host workloads")
        plan = limits(cfg)
        st.write(f"Hard duration: {plan['seconds']} s. CPU: {plan['cpu_duty']:.0%} duty cycle of one core. Memory: {plan['memory_mb']} MiB. Disk: {plan['disk_file_mb']} MiB temporary file, at most {plan['disk_total_write_mb']} MiB written. Processes: {plan['children']} sleeping children.")
        st.caption("These conservative workloads may be too small to trigger an anomaly, especially on powerful machines. A known workload is not a confirmed failure.")
        selected = st.selectbox("Local workload", KINDS)
        confirmed = st.checkbox("I confirm starting this bounded workload on this machine")
        is_current = session and repo.session()["id"] == session["id"]
        allowed = confirmed and is_current and status not in ("Offline", "Stale data", "Collector error")
        if st.button("Start bounded workload", disabled=not allowed):
            event = launch(repo, cfg, selected, session["id"])
            st.success(f"Workload requested: {event[:8]}. Actual timestamps appear below.")
        if not is_current or status in ("Offline", "Stale data", "Collector error"):
            st.info("Start the collector and select its current session before recording a local demonstration.")
        jobs = repo.workloads(limit=20)
        if jobs:
            st.dataframe(pd.DataFrame(localize_timestamps(jobs))[["id", "scenario", "status", "requested_at", "started_at", "ended_at", "error"]], hide_index=True, width="stretch")
            running = [j for j in jobs if j["status"] in ("running", "pending")]
            if running:
                chosen = st.selectbox("Workload to cancel", [j["id"] for j in running])
                if st.button("Request cancellation"):
                    repo.update_workload(chosen, cancel_requested=1)
                    st.info("Cancellation requested; the controller checks every 100 ms between bounded actions.")
    with local:
        st.subheader("Evaluate recorded genuine telemetry")
        st.write("Choose the session in the sidebar, then calculate detector counts, workload latency, missed intervals, recovery and measured monitor overhead.")
        if session and st.button("Evaluate selected session"):
            st.session_state["local_report"] = (session["id"], evaluate_local(repo, session["id"]))
        report = st.session_state.get("local_report")
        if report and session and report[0] == session["id"]:
            st.json(localize_timestamps(report[1]))
            st.download_button("Download local evaluation", json.dumps(localize_timestamps(report[1]), indent=2), "local_evaluation.json", "application/json")
        st.caption("The planned 70-minute study has not been collected automatically. Unlabelled periods are presumed ordinary and may include unrecorded activity. See docs/EVALUATION.md.")


def system_info(repo, session, cfg):
    latest, _ = header(repo, session, cfg, "System information")
    left, right = st.columns(2)
    with left.container(border=True):
        st.subheader("Monitored host")
        if session:
            st.json(localize_timestamps(json.loads(session["metadata_json"])))
            st.caption(f"Session: {session['id']} · Started: {format_time(session['started_at'])} · Source: {session['source']}")
        else:
            st.caption("Host metadata appears when the collector starts.")
    with right.container(border=True):
        st.subheader("Operating systems connections")
        st.markdown("**CPU** — processor utilization reflects scheduling and competing workloads.\n\n**RAM & swap** — allocation and virtual memory usage reveal resource pressure.\n\n**Disk** — cumulative I/O counters become read/write demand per elapsed second.\n\n**Processes** — the count tracks concurrent OS-managed workloads.\n\n**Concurrency** — one locked worker writes atomic records; dashboard readers use separate connections.\n\n**Persistence** — SQLite retains history in a local file across restarts.")
    with st.expander("Configuration used by this session"):
        st.json(json.loads(session["config_json"]) if session else {})
    with st.expander("Live process snapshot (this machine now)"):
        st.caption("Read-only snapshot, ranked by resident RAM. Processes may disappear or deny access.")
        if st.button("Read current processes"):
            st.dataframe(pd.DataFrame(top_processes()), hide_index=True, width="stretch")
    st.info("Statistical anomalies can be legitimate work. This engine cannot confirm a memory leak, identify an exact root cause, or predict a crash. Slow changes can be absorbed by the rolling baseline.")


PAGES = {"Overview": overview, "Resource explorer": resources, "Anomaly detection": anomalies,
         "Alert history": history, "Evaluation & demo lab": evaluation, "System information": system_info}
