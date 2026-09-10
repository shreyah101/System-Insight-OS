"""
Data Processing & Baseline Module
Cleans data, computes rolling statistical baselines, moving averages, standard deviations,
and trend slopes for early degradation analysis.
"""

from typing import Dict, Any, List, Optional
import numpy as np


class MetricsPreprocessor:
    """Computes dynamic baselines, rolling statistics, and trend features."""

    def __init__(self, window_size: int = 30):
        """
        :param window_size: Number of snapshots to maintain for rolling statistics (e.g. 30 samples).
        """
        self.window_size = window_size

    def compute_baselines(self, history: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
        """
        Computes rolling baseline stats (mean, std, min, max, slope)
        for critical system metrics across the historical window.
        """
        if not history:
            return {}

        metrics_keys = [
            "cpu_percent",
            "memory_percent",
            "swap_percent",
            "disk_percent",
            "disk_io_mb_sec",
            "process_count",
        ]

        baselines = {}
        for key in metrics_keys:
            values = [row[key] for row in history if key in row and row[key] is not None]
            if len(values) < 2:
                # Default fallback for initialization
                mean_val = float(values[0]) if values else 0.0
                baselines[key] = {
                    "mean": round(mean_val, 2),
                    "std": 1.0,
                    "min": round(mean_val, 2),
                    "max": round(mean_val, 2),
                    "slope": 0.0,
                    "count": len(values),
                }
                continue

            arr = np.array(values, dtype=np.float64)
            mean_val = float(np.mean(arr))
            std_val = float(np.std(arr))
            # If standard deviation is virtually zero (static metric), use a small floor to prevent division by zero
            safe_std = std_val if std_val > 0.01 else 1.0

            # Calculate linear regression slope: rate of change per sample (e.g. %/second)
            x = np.arange(len(arr))
            slope = float(np.polyfit(x, arr, 1)[0]) if len(arr) >= 3 else 0.0

            baselines[key] = {
                "mean": round(mean_val, 2),
                "std": round(safe_std, 2),
                "min": round(float(np.min(arr)), 2),
                "max": round(float(np.max(arr)), 2),
                "slope": round(slope, 4),
                "count": len(values),
            }

        return baselines

    def calculate_z_score(self, current_val: float, mean: float, std: float) -> float:
        """Calculates Z-Score (standard deviations away from normal baseline)."""
        if std <= 0.001:
            return 0.0
        return round((current_val - mean) / std, 2)

    def extract_features(self, metrics: Dict[str, Any], baselines: Optional[Dict[str, Dict[str, float]]] = None) -> np.ndarray:
        """
        Extracts multi-variate feature vector for Isolation Forest machine learning model.
        Features:
        [cpu_percent, memory_percent, swap_percent, disk_percent, disk_io_mb_sec, process_count]
        """
        return np.array([
            metrics["cpu"]["total_percent"],
            metrics["memory"]["percent"],
            metrics["swap"]["percent"],
            metrics["disk"]["percent"],
            metrics["disk"]["io_total_mb_sec"],
            metrics["processes"]["count"]
        ], dtype=np.float64).reshape(1, -1)
