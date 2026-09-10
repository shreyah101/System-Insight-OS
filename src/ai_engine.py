"""
AI Anomaly Detection Engine
Implements a Hybrid AI architecture:
1. Isolation Forest (Machine Learning) for multi-dimensional anomaly detection
2. Z-Score Statistical Analysis for dynamic threshold & spike detection
3. Trend Drift Analysis for early memory leak and runaway process detection
4. Composite System Health Scoring (0 - 100)
"""

import time
from typing import Dict, Any, List, Tuple, Optional
import numpy as np
from sklearn.ensemble import IsolationForest


class AIAnomalyDetector:
    """Hybrid AI Engine detecting OS performance degradation."""

    def __init__(self, contamination: float = 0.05):
        self.contamination = contamination
        self.model: IsolationForest = IsolationForest(
            n_estimators=100,
            contamination=self.contamination,
            random_state=42,
            n_jobs=-1
        )
        self.is_model_trained = False
        self._training_samples_buffer: List[List[float]] = []

    def train_or_update_model(self, history: List[Dict[str, Any]], current_vector: Optional[np.ndarray] = None):
        """
        Fits or retrains the Isolation Forest model using recent historical baseline vectors.
        """
        if len(history) < 15:
            # Bootstrap with normal operating envelope centered on current host metrics
            if current_vector is not None:
                curr = current_vector.flatten()
                center = [curr[0], curr[1], curr[2], curr[3], curr[4], curr[5]]
            else:
                center = [20.0, 45.0, 5.0, 50.0, 5.0, 200.0]

            synthetic_normal = np.random.normal(
                loc=center,
                scale=[10.0, 8.0, 3.0, 2.0, 5.0, 25.0],
                size=(60, 6)
            )
            synthetic_normal = np.clip(synthetic_normal, 0.0, None)
            self.model.fit(synthetic_normal)
            self.is_model_trained = True
            return

        features = []
        for row in history:
            features.append([
                row["cpu_percent"],
                row["memory_percent"],
                row["swap_percent"],
                row["disk_percent"],
                row["disk_io_mb_sec"],
                row["process_count"]
            ])

        X = np.array(features, dtype=np.float64)
        self.model.fit(X)
        self.is_model_trained = True

    def analyze(
        self,
        current_metrics: Dict[str, Any],
        baselines: Dict[str, Dict[str, float]],
        history: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Performs holistic AI analysis:
        Returns detected anomalies list, health score, and degradation assessment.
        """
        anomalies: List[Dict[str, Any]] = []
        penalties: float = 0.0
        now_ts = current_metrics["timestamp"]
        iso_ts = current_metrics["iso_time"]

        cpu_val = current_metrics["cpu"]["total_percent"]
        mem_val = current_metrics["memory"]["percent"]
        swap_val = current_metrics["swap"]["percent"]
        disk_val = current_metrics["disk"]["percent"]
        disk_io_val = current_metrics["disk"]["io_total_mb_sec"]
        proc_val = current_metrics["processes"]["count"]

        # Feature vector for ML
        feature_vector = np.array([[
            cpu_val, mem_val, swap_val, disk_val, disk_io_val, proc_val
        ]], dtype=np.float64)

        # -------------------------------------------------------------
        # 1. Isolation Forest Machine Learning Inference
        # -------------------------------------------------------------
        ml_is_anomaly = False
        ml_anomaly_score = 0.0

        if not self.is_model_trained or len(history) >= 15:
            self.train_or_update_model(history, current_vector=feature_vector)

        try:
            prediction = self.model.predict(feature_vector)[0]  # -1 = anomaly, 1 = normal
            # score_samples returns opposite of anomaly score (lower means more anomalous)
            raw_score = self.model.score_samples(feature_vector)[0]
            # Normalize to 0 (normal) to 1 (highly anomalous)
            ml_anomaly_score = round(float(np.clip(-raw_score, 0.0, 1.0)), 3)

            if prediction == -1:
                ml_is_anomaly = True
                penalties += 25.0 * ml_anomaly_score
                anomalies.append({
                    "timestamp": now_ts,
                    "iso_time": iso_ts,
                    "metric_name": "Multi-Variate System Vector",
                    "current_value": ml_anomaly_score,
                    "baseline_mean": None,
                    "baseline_std": None,
                    "z_score": None,
                    "detector": "Isolation Forest (ML)",
                    "severity": "WARNING" if ml_anomaly_score < 0.65 else "CRITICAL",
                    "description": f"AI model detected unusual combination of system metrics (Anomaly Score: {ml_anomaly_score})."
                })
        except Exception:
            ml_is_anomaly = False

        # -------------------------------------------------------------
        # 2. Statistical Z-Score & Dynamic Threshold Analysis
        # -------------------------------------------------------------
        metric_checks = [
            ("cpu_percent", cpu_val, "CPU Usage", "%", 85.0, 95.0),
            ("memory_percent", mem_val, "RAM Usage", "%", 85.0, 95.0),
            ("swap_percent", swap_val, "Swap Usage", "%", 40.0, 75.0),
            ("disk_io_mb_sec", disk_io_val, "Disk I/O Rate", "MB/s", 50.0, 120.0),
            ("process_count", proc_val, "Process Count", "procs", 400.0, 600.0),
        ]

        for key, val, label, unit, warn_thresh, crit_thresh in metric_checks:
            base = baselines.get(key, {})
            mean = base.get("mean", val)
            std = base.get("std", 1.0)
            z = round((val - mean) / std, 2) if std > 0.01 else 0.0

            # Condition A: Statistical anomaly (Z-Score > 2.5)
            # Condition B: High absolute stress (val > warn_thresh)
            is_stat_anomaly = abs(z) >= 2.5
            is_threshold_breach = val >= warn_thresh

            if is_stat_anomaly or is_threshold_breach:
                is_crit = (abs(z) >= 3.5) or (val >= crit_thresh)
                severity = "CRITICAL" if is_crit else "WARNING"
                penalty_amount = 20.0 if is_crit else 10.0
                penalties += penalty_amount

                reason = (
                    f"{label} is {val}{unit} (Baseline: {mean:.1f}{unit}, Z-Score: {z:+0.2f}σ)."
                    if is_stat_anomaly else
                    f"{label} reached high load threshold: {val}{unit}."
                )

                anomalies.append({
                    "timestamp": now_ts,
                    "iso_time": iso_ts,
                    "metric_name": label,
                    "current_value": round(val, 2),
                    "baseline_mean": mean,
                    "baseline_std": std,
                    "z_score": z,
                    "detector": "Z-Score Analysis",
                    "severity": severity,
                    "description": reason
                })

        # -------------------------------------------------------------
        # 3. Early Performance Degradation: Memory Leak / Upward Drift
        # -------------------------------------------------------------
        mem_base = baselines.get("memory_percent", {})
        mem_slope = mem_base.get("slope", 0.0)
        # If memory is continuously increasing at slope >= 0.15% per sample over history
        if mem_slope >= 0.15 and len(history) >= 10:
            penalties += 20.0
            est_minutes = round((100.0 - mem_val) / (mem_slope * 60.0), 1) if mem_slope > 0 else 999.0
            time_msg = f"RAM exhaustion predicted in ~{max(1.0, est_minutes)} min" if est_minutes < 120 else "Continuous memory growth observed"
            anomalies.append({
                "timestamp": now_ts,
                "iso_time": iso_ts,
                "metric_name": "RAM Trend (Memory Leak)",
                "current_value": round(mem_slope, 3),
                "baseline_mean": mem_base.get("mean"),
                "baseline_std": mem_base.get("std"),
                "z_score": None,
                "detector": "Trend Drift Analysis",
                "severity": "WARNING" if est_minutes > 15 else "CRITICAL",
                "description": f"Early warning: Sustained memory climb detected (+{mem_slope:.2f}%/step). {time_msg}."
            })

        # -------------------------------------------------------------
        # 4. Composite System Health Score (0 - 100)
        # -------------------------------------------------------------
        health_score = max(5.0, round(100.0 - penalties, 1))

        if health_score >= 80.0:
            health_status = "Optimal"
            status_color = "#10b981"  # Emerald green
        elif health_score >= 50.0:
            health_status = "Degraded"
            status_color = "#f59e0b"  # Amber warning
        else:
            health_status = "Critical Degradation"
            status_color = "#ef4444"  # Red alert

        return {
            "health_score": health_score,
            "health_status": health_status,
            "status_color": status_color,
            "anomalies": anomalies,
            "ml_anomaly_score": ml_anomaly_score,
            "is_anomaly_detected": len(anomalies) > 0,
            "timestamp": now_ts,
        }
