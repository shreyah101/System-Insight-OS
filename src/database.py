"""
Database Management Module
Manages SQLite schema, metrics persistence, and historical queries.
"""

import os
import sqlite3
from typing import Dict, Any, List, Optional


class DatabaseManager:
    """Handles persistent SQLite storage for health metrics, anomalies, and alerts."""

    def __init__(self, db_path: str = "data/health_monitor.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes database tables with appropriate indexes."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Metrics History Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metrics_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    iso_time TEXT NOT NULL,
                    cpu_percent REAL NOT NULL,
                    memory_percent REAL NOT NULL,
                    memory_used_gb REAL NOT NULL,
                    swap_percent REAL NOT NULL,
                    disk_percent REAL NOT NULL,
                    disk_io_mb_sec REAL NOT NULL,
                    network_mb_sec REAL NOT NULL,
                    process_count INTEGER NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics_history(timestamp)")

            # 2. Anomalies Log Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS anomalies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    iso_time TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    current_value REAL NOT NULL,
                    baseline_mean REAL,
                    baseline_std REAL,
                    z_score REAL,
                    detector TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    description TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_anomalies_ts ON anomalies(timestamp)")

            # 3. Alerts Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    iso_time TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    action_recommendation TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(timestamp)")

            conn.commit()

    def insert_metric(self, metrics: Dict[str, Any]):
        """Inserts a new metrics snapshot into the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO metrics_history (
                    timestamp, iso_time, cpu_percent, memory_percent,
                    memory_used_gb, swap_percent, disk_percent,
                    disk_io_mb_sec, network_mb_sec, process_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metrics["timestamp"],
                metrics["iso_time"],
                metrics["cpu"]["total_percent"],
                metrics["memory"]["percent"],
                metrics["memory"]["used_gb"],
                metrics["swap"]["percent"],
                metrics["disk"]["percent"],
                metrics["disk"]["io_total_mb_sec"],
                round(metrics["network"]["recv_mb_sec"] + metrics["network"]["sent_mb_sec"], 2),
                metrics["processes"]["count"]
            ))
            conn.commit()

    def get_recent_metrics(self, limit: int = 60) -> List[Dict[str, Any]]:
        """Returns the most recent N metric snapshots in chronological order."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM (
                    SELECT * FROM metrics_history ORDER BY timestamp DESC LIMIT ?
                ) ORDER BY timestamp ASC
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def insert_anomaly(self, anomaly: Dict[str, Any]):
        """Records a detected anomaly."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO anomalies (
                    timestamp, iso_time, metric_name, current_value,
                    baseline_mean, baseline_std, z_score, detector,
                    severity, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                anomaly["timestamp"],
                anomaly["iso_time"],
                anomaly["metric_name"],
                anomaly["current_value"],
                anomaly.get("baseline_mean"),
                anomaly.get("baseline_std"),
                anomaly.get("z_score"),
                anomaly["detector"],
                anomaly["severity"],
                anomaly["description"]
            ))
            conn.commit()

    def get_recent_anomalies(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Returns the most recent N anomaly occurrences."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM anomalies ORDER BY timestamp DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def insert_alert(self, alert: Dict[str, Any]):
        """Logs an alert event."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alerts (
                    timestamp, iso_time, severity, title, message, action_recommendation
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                alert["timestamp"],
                alert["iso_time"],
                alert["severity"],
                alert["title"],
                alert["message"],
                alert.get("action_recommendation", "")
            ))
            conn.commit()

    def get_recent_alerts(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Returns the most recent alerts."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def clear_history(self):
        """Clears all stored metrics, anomalies, and alerts (for reset/demo)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM metrics_history")
            cursor.execute("DELETE FROM anomalies")
            cursor.execute("DELETE FROM alerts")
            conn.commit()
