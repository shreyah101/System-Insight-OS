"""
Flask Application Server
Hosts the AI-Based System Health Monitoring Engine dashboard and real-time SSE stream.
"""

import os
import json
import time
import threading
from io import StringIO
import csv
from flask import Flask, render_template, jsonify, Response, request
from flask_cors import CORS

from src.collector import SystemMetricsCollector
from src.database import DatabaseManager
from src.preprocessor import MetricsPreprocessor
from src.ai_engine import AIAnomalyDetector
from src.alert_manager import AlertManager
from src.simulator import WorkloadSimulator

app = Flask(__name__)
CORS(app)

# Core Engine Singletons
collector = SystemMetricsCollector()
db = DatabaseManager()
preprocessor = MetricsPreprocessor(window_size=45)
detector = AIAnomalyDetector(contamination=0.05)
alert_mgr = AlertManager(db)
simulator = WorkloadSimulator()

# Thread-safe global state cache
state_lock = threading.Lock()
latest_state = {
    "metrics": None,
    "baselines": {},
    "analysis": {
        "health_score": 100.0,
        "health_status": "Optimal",
        "status_color": "#10b981",
        "anomalies": [],
        "ml_anomaly_score": 0.0,
        "is_anomaly_detected": False,
    },
    "alerts": []
}


def background_monitor_worker():
    """Continuous background loop collecting system metrics and running AI inference."""
    print("[+] Background System Health Monitor started.")
    while True:
        try:
            # 1. Collect OS metrics
            metrics = collector.collect()

            # 2. Store metrics in DB
            db.insert_metric(metrics)

            # 3. Retrieve recent history for rolling baseline
            history = db.get_recent_metrics(limit=preprocessor.window_size)

            # 4. Calculate baseline statistics
            baselines = preprocessor.compute_baselines(history)

            # 5. AI Anomaly & Degradation Analysis
            analysis = detector.analyze(metrics, baselines, history)

            # 6. Process and log anomalies & alerts
            new_alerts = alert_mgr.process_anomalies(analysis["anomalies"], metrics)

            # 7. Update latest in-memory state
            with state_lock:
                latest_state["metrics"] = metrics
                latest_state["baselines"] = baselines
                latest_state["analysis"] = analysis
                latest_state["alerts"] = db.get_recent_alerts(limit=15)

        except Exception as e:
            print(f"[!] Error in monitor worker loop: {e}")

        time.sleep(1.0)


# Start monitor thread as daemon
monitor_thread = threading.Thread(target=background_monitor_worker, daemon=True)
monitor_thread.start()


@app.route("/")
def index():
    """Renders the main glassmorphic real-time health dashboard."""
    return render_template("index.html")


@app.route("/api/live")
def get_live():
    """Returns the latest metric snapshot and AI analysis."""
    with state_lock:
        if latest_state["metrics"] is None:
            # Fallback if first tick hasn't executed yet
            first_metrics = collector.collect()
            return jsonify({
                "metrics": first_metrics,
                "baselines": {},
                "analysis": latest_state["analysis"],
                "alerts": []
            })
        return jsonify(latest_state)


@app.route("/api/history")
def get_history():
    """Returns recent metrics history for initial graph rendering."""
    limit = request.args.get("limit", default=40, type=int)
    history = db.get_recent_metrics(limit=limit)
    return jsonify(history)


@app.route("/api/anomalies")
def get_anomalies():
    """Returns detected anomalies log."""
    limit = request.args.get("limit", default=30, type=int)
    return jsonify(db.get_recent_anomalies(limit=limit))


@app.route("/api/alerts")
def get_alerts():
    """Returns recent alerts."""
    limit = request.args.get("limit", default=20, type=int)
    return jsonify(db.get_recent_alerts(limit=limit))


@app.route("/api/stream")
def sse_stream():
    """Server-Sent Events stream for live real-time chart updates without polling."""
    def event_generator():
        while True:
            with state_lock:
                data = json.dumps(latest_state)
            yield f"data: {data}\n\n"
            time.sleep(1.0)

    return Response(event_generator(), mimetype="text/event-stream")


@app.route("/api/simulate/<action>", methods=["POST"])
def trigger_simulation(action: str):
    """
    Triggers simulated workloads for viva and live demo verification:
    - cpu: Spikes CPU usage
    - memory: Simulates memory leak
    - disk: Simulates heavy disk I/O burst
    - stop: Stops any active stressor
    """
    duration = request.args.get("duration", default=6, type=int)
    if action == "cpu":
        res = simulator.simulate_cpu_spike(duration_sec=duration)
    elif action == "memory":
        res = simulator.simulate_memory_leak(duration_sec=duration)
    elif action == "disk":
        res = simulator.simulate_disk_io(duration_sec=duration)
    elif action == "stop":
        simulator.stop_all()
        res = {"status": "stopped", "message": "All simulated workloads terminated."}
    else:
        return jsonify({"error": f"Unknown simulation type '{action}'"}), 400

    return jsonify(res)


@app.route("/api/clear", methods=["POST"])
def clear_db():
    """Clears metric and anomaly history."""
    db.clear_history()
    return jsonify({"status": "cleared", "message": "History cleared successfully."})


@app.route("/api/export")
def export_csv():
    """Exports metrics history as CSV."""
    records = db.get_recent_metrics(limit=200)
    if not records:
        return "No records to export", 400

    si = StringIO()
    writer = csv.DictWriter(si, fieldnames=records[0].keys())
    writer.writeheader()
    writer.writerows(records)

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=system_health_report.csv"}
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
