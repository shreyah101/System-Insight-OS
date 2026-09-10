"""
Streamlit Dashboard for AI-Based System Health Monitoring Engine
Alternative UI matching the same underlying AI detection engine and database.
Run with: streamlit run app_streamlit.py
"""

import time
import pandas as pd
import streamlit as st

from src.collector import SystemMetricsCollector
from src.database import DatabaseManager
from src.preprocessor import MetricsPreprocessor
from src.ai_engine import AIAnomalyDetector
from src.simulator import WorkloadSimulator

# Page Configuration
st.set_page_config(
    page_title="AI System Health Engine",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Session Singletons
if "collector" not in st.session_state:
    st.session_state.collector = SystemMetricsCollector()
    st.session_state.db = DatabaseManager()
    st.session_state.preprocessor = MetricsPreprocessor(window_size=35)
    st.session_state.detector = AIAnomalyDetector(contamination=0.05)
    st.session_state.simulator = WorkloadSimulator()

collector = st.session_state.collector
db = st.session_state.db
preprocessor = st.session_state.preprocessor
detector = st.session_state.detector
simulator = st.session_state.simulator

# Sidebar: Viva Demo Simulation Controls
with st.sidebar:
    st.title("⚡ Viva Demo Controls")
    st.caption("Trigger controlled workloads to demonstrate AI anomaly detection in real-time.")

    if st.button("🔥 Simulate CPU Spike", use_container_width=True):
        res = simulator.simulate_cpu_spike(duration_sec=6)
        st.warning(res["message"])

    if st.button("💧 Simulate Memory Leak", use_container_width=True):
        res = simulator.simulate_memory_leak(duration_sec=8)
        st.warning(res["message"])

    if st.button("💾 Burst Disk I/O", use_container_width=True):
        res = simulator.simulate_disk_io(duration_sec=5)
        st.warning(res["message"])

    if st.button("🛑 Stop All Stressors", use_container_width=True):
        simulator.stop_all()
        st.info("Stressors terminated.")

    st.markdown("---")
    refresh_rate = st.slider("Live Refresh Rate (seconds)", min_value=1, max_value=5, value=1)
    auto_refresh = st.checkbox("Auto Refresh", value=True)

# Main Dashboard Header
st.title("🛡️ AI-Based System Health Monitoring Engine")
st.markdown("### Early Detection of Operating System Performance Degradation")
st.caption("Powered by `psutil`, `Isolation Forest` (Unsupervised ML), `Z-Score Analysis`, and `Linear Trend Drift`")

# Collect current snapshot
metrics = collector.collect()
db.insert_metric(metrics)
history = db.get_recent_metrics(limit=preprocessor.window_size)
baselines = preprocessor.compute_baselines(history)
analysis = detector.analyze(metrics, baselines, history)

# Top Health Score Banner
score = analysis["health_score"]
status = analysis["health_status"]

if score >= 80:
    st.success(f"### System Health Score: **{score:.1f} / 100** — Status: **{status}**")
elif score >= 50:
    st.warning(f"### System Health Score: **{score:.1f} / 100** — Status: **{status} (Early Degradation Warning)**")
else:
    st.error(f"### System Health Score: **{score:.1f} / 100** — Status: **{status} (Critical Bottleneck)**")

# 4 Key Metrics in Columns
col1, col2, col3, col4 = st.columns(4)

cpu_val = metrics["cpu"]["total_percent"]
cpu_base = baselines.get("cpu_percent", {}).get("mean", cpu_val)
cpu_delta = round(cpu_val - cpu_base, 1)

mem_val = metrics["memory"]["percent"]
mem_base = baselines.get("memory_percent", {}).get("mean", mem_val)
mem_delta = round(mem_val - mem_base, 1)

disk_val = metrics["disk"]["percent"]
disk_io = metrics["disk"]["io_total_mb_sec"]
procs_count = metrics["processes"]["count"]

col1.metric("CPU Utilisation", f"{cpu_val:.1f}%", f"{cpu_delta:+} vs baseline", delta_color="inverse")
col2.metric("RAM (Memory)", f"{mem_val:.1f}%", f"{mem_delta:+} vs baseline", delta_color="inverse")
col3.metric("Disk I/O Rate", f"{disk_io:.1f} MB/s", f"{disk_val:.1f}% Storage Full")
col4.metric("Active Processes", f"{procs_count}", f"Swap: {metrics['swap']['percent']}%")

# Middle: Historical Performance Trend Graphs
st.markdown("---")
st.subheader("📈 Live Metrics vs. Dynamic Baseline")

if len(history) >= 2:
    df_hist = pd.DataFrame(history)
    df_hist["Time"] = df_hist["iso_time"].apply(lambda x: x.split(" ")[1] if " " in x else x)

    tab1, tab2, tab3 = st.tabs(["CPU Usage Trend", "Memory (RAM) Trend", "Disk I/O Activity"])

    with tab1:
        st.line_chart(df_hist.set_index("Time")[["cpu_percent"]], height=240)
    with tab2:
        st.line_chart(df_hist.set_index("Time")[["memory_percent"]], height=240)
    with tab3:
        st.line_chart(df_hist.set_index("Time")[["disk_io_mb_sec"]], height=240)

# Bottom: Detected Anomalies & Top Processes
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("🚨 Detected AI Anomalies")
    recent_anomalies = db.get_recent_anomalies(limit=10)
    if recent_anomalies:
        for a in recent_anomalies:
            sev = a["severity"]
            ts = a["iso_time"].split(" ")[1] if " " in a["iso_time"] else a["iso_time"]
            if sev == "CRITICAL":
                st.error(f"**[{ts}] {a['metric_name']}** ({a['detector']}): {a['description']}")
            elif sev == "WARNING":
                st.warning(f"**[{ts}] {a['metric_name']}** ({a['detector']}): {a['description']}")
            else:
                st.info(f"**[{ts}] {a['metric_name']}** ({a['detector']}): {a['description']}")
    else:
        st.info("No anomalies detected. System operating inside normal envelope.")

with col_right:
    st.subheader("⚙️ Top 5 Resource-Consuming Processes")
    top_p = metrics["processes"]["top"]
    if top_p:
        df_proc = pd.DataFrame(top_p)[["pid", "name", "cpu_percent", "memory_percent", "status"]]
        df_proc.columns = ["PID", "Process Name", "CPU %", "RAM %", "Status"]
        st.dataframe(df_proc, use_container_width=True, hide_index=True)
    else:
        st.write("Scanning processes...")

# Auto refresh trigger
if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
