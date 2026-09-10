"""
Alert & Logging Module
Manages alert throttling, logging to file, SQLite persistence, and diagnostic advice.
"""

import os
import time
import logging
from typing import Dict, Any, List
from src.database import DatabaseManager


class AlertManager:
    """Handles alert generation, severity triage, debouncing, and multi-channel logging."""

    def __init__(self, db: DatabaseManager, log_file: str = "logs/system_health.log", debounce_seconds: float = 8.0):
        self.db = db
        self.log_file = log_file
        self.debounce_seconds = debounce_seconds
        self._last_alert_times: Dict[str, float] = {}

        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        self._setup_logger()

    def _setup_logger(self):
        self.logger = logging.getLogger("SystemHealthMonitor")
        self.logger.setLevel(logging.INFO)

        # Avoid adding handlers multiple times
        if not self.logger.handlers:
            formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def process_anomalies(self, anomalies: List[Dict[str, Any]], current_metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Filters, stores, and logs anomalies, generating alerts when appropriate.
        Returns list of newly triggered alerts.
        """
        now = time.time()
        triggered_alerts = []

        top_procs = current_metrics.get("processes", {}).get("top", [])
        top_proc_hint = f" Top consumer: {top_procs[0]['name']} (PID {top_procs[0]['pid']}, CPU: {top_procs[0]['cpu_percent']}%, RAM: {top_procs[0]['memory_percent']}%)" if top_procs else ""

        for anomaly in anomalies:
            metric = anomaly["metric_name"]
            severity = anomaly["severity"]

            # Store each raw anomaly in the database
            self.db.insert_anomaly(anomaly)

            # Debounce to prevent flooding UI / logs with identical alerts every second
            last_time = self._last_alert_times.get(metric, 0)
            if now - last_time < self.debounce_seconds:
                continue

            self._last_alert_times[metric] = now

            # Determine action recommendation
            action_rec = self._generate_recommendation(metric, severity, top_proc_hint)

            alert_payload = {
                "timestamp": anomaly["timestamp"],
                "iso_time": anomaly["iso_time"],
                "severity": severity,
                "title": f"{severity}: Unusual {metric} Detected",
                "message": anomaly["description"] + top_proc_hint,
                "action_recommendation": action_rec
            }

            # Save alert to DB
            self.db.insert_alert(alert_payload)
            triggered_alerts.append(alert_payload)

            # Write to file log
            log_msg = f"{alert_payload['title']} | {alert_payload['message']} | Recommendation: {action_rec}"
            if severity == "CRITICAL":
                self.logger.critical(log_msg)
            elif severity == "WARNING":
                self.logger.warning(log_msg)
            else:
                self.logger.info(log_msg)

        return triggered_alerts

    def _generate_recommendation(self, metric: str, severity: str, top_proc_hint: str) -> str:
        """Returns actionable advice based on metric type."""
        m_lower = metric.lower()
        if "cpu" in m_lower:
            return f"Inspect runaway tasks or terminate high CPU process.{top_proc_hint}"
        elif "ram" in m_lower or "memory" in m_lower:
            return f"Check for memory leaks. Consider restarting long-running applications.{top_proc_hint}"
        elif "disk" in m_lower:
            return "Heavy disk I/O detected. Defer large file transfers or indexers."
        elif "swap" in m_lower:
            return "Swap paging is high; physical RAM is saturated. Free up memory immediately."
        elif "vector" in m_lower:
            return "System workload profile significantly deviates from baseline behavior."
        return "Observe system performance and monitor process activity."
