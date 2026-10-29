from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from src.models import Decision, METRICS, SEVERITY_ORDER, Severity, utc_now

SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_sessions (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
 heartbeat TEXT, status TEXT NOT NULL, error TEXT, metadata_json TEXT NOT NULL,
 config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metrics_history (
 id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES monitor_sessions(id),
 timestamp TEXT NOT NULL, cpu_percent REAL, ram_percent REAL, disk_read_bps REAL,
 disk_write_bps REAL, process_count REAL, swap_percent REAL,
 severity TEXT NOT NULL, ready INTEGER NOT NULL, z_flag INTEGER NOT NULL,
 forest_flag INTEGER NOT NULL, forest_score REAL, decision_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_session_time ON metrics_history(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_time ON metrics_history(timestamp);
CREATE TABLE IF NOT EXISTS alerts (
 id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES monitor_sessions(id),
 first_sample_id INTEGER NOT NULL REFERENCES metrics_history(id),
 last_sample_id INTEGER NOT NULL REFERENCES metrics_history(id),
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, resolved_at TEXT,
 severity TEXT NOT NULL, status TEXT NOT NULL, occurrence_count INTEGER NOT NULL,
 recovery_count INTEGER NOT NULL DEFAULT 0, z_flag INTEGER NOT NULL, forest_flag INTEGER NOT NULL,
 affected_json TEXT NOT NULL, explanation TEXT NOT NULL, evidence_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_session_status ON alerts(session_id, status);
CREATE INDEX IF NOT EXISTS idx_alerts_time ON alerts(first_seen);
CREATE TABLE IF NOT EXISTS workload_events (
 id TEXT PRIMARY KEY, session_id TEXT REFERENCES monitor_sessions(id), scenario TEXT NOT NULL,
 requested_at TEXT NOT NULL, started_at TEXT, ended_at TEXT, status TEXT NOT NULL,
 cancel_requested INTEGER NOT NULL DEFAULT 0, limits_json TEXT NOT NULL, error TEXT
);
"""


def json_dumps(value) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


class Repository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    def start_session(self, metadata: dict, config: dict, source: str = "live", recover_abandoned: bool = False) -> str:
        session_id = str(uuid4())
        now = utc_now().isoformat()
        with self.connection() as conn:
            if recover_abandoned:
                # Called only after exclusive worker lock acquisition. A crash is not recovery.
                conn.execute("UPDATE monitor_sessions SET status='interrupted', ended_at=heartbeat WHERE source=? AND status IN ('running','error')", (source,))
            conn.execute("INSERT INTO monitor_sessions VALUES (?,?,?,?,?,?,?,?,?)",
                         (session_id, source, now, None, now, "running", None, json_dumps(metadata), json_dumps(config)))
        return session_id

    def finish_session(self, session_id: str, status: str = "stopped", error: str | None = None):
        with self.connection() as conn:
            conn.execute("UPDATE monitor_sessions SET ended_at=?,status=?,error=? WHERE id=?", (utc_now().isoformat(), status, error, session_id))

    def mark_error(self, session_id: str, error: str):
        with self.connection() as conn:
            conn.execute("UPDATE monitor_sessions SET status='error',error=?,heartbeat=? WHERE id=?", (error, utc_now().isoformat(), session_id))

    def save(self, session_id: str, decision: Decision, recovery_samples: int) -> int:
        payload = decision.to_dict()
        timestamp = payload["sample"]["timestamp"]
        with self.connection() as conn:
            cur = conn.execute(f"INSERT INTO metrics_history (session_id,timestamp,{','.join(METRICS)},severity,ready,z_flag,forest_flag,forest_score,decision_json) VALUES ({','.join('?' for _ in range(14))})",
                               (session_id, timestamp, *(decision.sample.values[k] for k in METRICS), decision.severity.value, int(decision.ready), int(decision.zscore.anomaly), int(decision.forest.anomaly), decision.forest.score, json_dumps(payload)))
            sample_id = cur.lastrowid
            self._update_episode(conn, session_id, sample_id, decision, recovery_samples)
            conn.execute("UPDATE monitor_sessions SET heartbeat=?,status='running',error=NULL WHERE id=?", (timestamp, session_id))
        return sample_id

    @staticmethod
    def _update_episode(conn, session_id, sample_id, decision, recovery_samples):
        # One host-wide episode per session: any anomaly before five valid recoveries continues it.
        active = conn.execute("SELECT * FROM alerts WHERE session_id=? AND status='Active' ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
        timestamp = decision.sample.timestamp.isoformat()
        if decision.ready and decision.severity != Severity.NORMAL:
            affected = decision.zscore.flagged or list(decision.features)
            evidence = json_dumps(decision.to_dict())
            if active:
                peak = max((Severity(active["severity"]), decision.severity), key=SEVERITY_ORDER.index).value
                affected = sorted(set(json.loads(active["affected_json"])) | set(affected))
                conn.execute("UPDATE alerts SET last_sample_id=?,last_seen=?,severity=?,occurrence_count=occurrence_count+1,recovery_count=0,z_flag=?,forest_flag=?,affected_json=?,explanation=?,evidence_json=? WHERE id=?",
                             (sample_id, timestamp, peak, int(active["z_flag"] or decision.zscore.anomaly), int(active["forest_flag"] or decision.forest.anomaly), json_dumps(affected), decision.explanation, evidence, active["id"]))
            else:
                conn.execute("INSERT INTO alerts (session_id,first_sample_id,last_sample_id,first_seen,last_seen,severity,status,occurrence_count,z_flag,forest_flag,affected_json,explanation,evidence_json) VALUES (?,?,?,?,?,?,'Active',1,?,?,?,?,?)",
                             (session_id, sample_id, sample_id, timestamp, timestamp, decision.severity.value, int(decision.zscore.anomaly), int(decision.forest.anomaly), json_dumps(affected), decision.explanation, evidence))
        elif active:
            # Missing / warm-up samples break consecutive recovery; they cannot prove resolution.
            count = active["recovery_count"] + 1 if decision.ready else 0
            resolved = count >= recovery_samples
            conn.execute("UPDATE alerts SET recovery_count=?,status=?,resolved_at=? WHERE id=?", (count, "Resolved" if resolved else "Active", timestamp if resolved else None, active["id"]))

    def session(self, session_id: str | None = None, source: str = "live") -> dict | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM monitor_sessions WHERE id=?", (session_id,)).fetchone() if session_id else conn.execute("SELECT * FROM monitor_sessions WHERE source=? ORDER BY started_at DESC LIMIT 1", (source,)).fetchone()
        return dict(row) if row else None

    def sessions(self, source: str = "live", limit: int = 100) -> list[dict]:
        with self.connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM monitor_sessions WHERE source=? ORDER BY started_at DESC LIMIT ?", (source, limit))]

    def metrics(self, session_id: str, start: str | None = None, end: str | None = None, limit: int = 1800) -> list[dict]:
        sql, args = "SELECT * FROM metrics_history WHERE session_id=?", [session_id]
        if start:
            sql += " AND timestamp>=?"
            args.append(start)
        if end:
            sql += " AND timestamp<=?"
            args.append(end)
        sql += " ORDER BY timestamp DESC,id DESC LIMIT ?"
        args.append(limit)
        with self.connection() as conn:
            return [dict(r) for r in reversed(conn.execute(sql, args).fetchall())]

    def alerts(self, session_id: str | None = None, severity: str | None = None, detector: str | None = None, start: str | None = None, end: str | None = None, limit: int = 500) -> list[dict]:
        sql, args = "SELECT * FROM alerts WHERE 1=1", []
        for key, value, op in (("session_id", session_id, "="), ("severity", severity, "="), ("first_seen", start, ">="), ("first_seen", end, "<=")):
            if value:
                sql += f" AND {key}{op}?"
                args.append(value)
        if detector in ("zscore", "forest"):
            sql += " AND " + ("z_flag" if detector == "zscore" else "forest_flag") + "=1"
        sql += " ORDER BY first_seen DESC,id DESC LIMIT ?"
        args.append(limit)
        with self.connection() as conn:
            return [dict(r) for r in conn.execute(sql, args)]

    def active(self, session_id: str) -> bool:
        with self.connection() as conn:
            return conn.execute("SELECT 1 FROM alerts WHERE session_id=? AND status='Active' LIMIT 1", (session_id,)).fetchone() is not None

    def summary(self, session_id: str) -> dict:
        with self.connection() as conn:
            samples = dict(conn.execute("SELECT COUNT(*) AS samples,SUM(ready) AS eligible,SUM(z_flag) AS z_detections,SUM(forest_flag) AS forest_detections,MIN(timestamp) AS first_sample,MAX(timestamp) AS last_sample FROM metrics_history WHERE session_id=?", (session_id,)).fetchone())
            samples["severities"] = {r[0]: r[1] for r in conn.execute("SELECT severity,COUNT(*) FROM alerts WHERE session_id=? GROUP BY severity", (session_id,))}
            samples["episodes"] = {r[0]: r[1] for r in conn.execute("SELECT status,COUNT(*) FROM alerts WHERE session_id=? GROUP BY status", (session_id,))}
        return samples

    def export_metrics(self, session_id: str) -> str:
        # Stream rows through a cursor; export is deliberate and is never part of UI refresh.
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM metrics_history WHERE session_id=? ORDER BY timestamp,id", (session_id,))
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow([c[0] for c in rows.description])
            writer.writerows(rows)
        return output.getvalue()

    def create_workload(self, scenario: str, limits: dict, session_id: str | None) -> str:
        event_id = str(uuid4())
        with self.connection() as conn:
            conn.execute("INSERT INTO workload_events (id,session_id,scenario,requested_at,status,limits_json) VALUES (?,?,?,?,'pending',?)", (event_id, session_id, scenario, utc_now().isoformat(), json_dumps(limits)))
        return event_id

    def workloads(self, session_id: str | None = None, limit: int = 100) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM workload_events WHERE session_id=? ORDER BY requested_at DESC LIMIT ?", (session_id, limit)) if session_id else conn.execute("SELECT * FROM workload_events ORDER BY requested_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in rows]

    def workload(self, event_id: str) -> dict:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM workload_events WHERE id=?", (event_id,)).fetchone()
            if not row:
                raise ValueError("Workload event not found")
            return dict(row)

    def update_workload(self, event_id: str, **values):
        allowed = {"started_at", "ended_at", "status", "cancel_requested", "error"}
        if not values or not set(values) <= allowed:
            raise ValueError("Invalid workload update")
        with self.connection() as conn:
            conn.execute(f"UPDATE workload_events SET {','.join(k+'=?' for k in values)} WHERE id=?", (*values.values(), event_id))
