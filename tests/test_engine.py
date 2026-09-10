"""
Automated Unit Tests for AI-Based System Health Monitoring Engine
Tests metric collector, preprocessor, AI anomaly detector, database, and alert manager.
"""

import os
import unittest
import numpy as np

from src.collector import SystemMetricsCollector
from src.database import DatabaseManager
from src.preprocessor import MetricsPreprocessor
from src.ai_engine import AIAnomalyDetector
from src.alert_manager import AlertManager


class TestSystemHealthEngine(unittest.TestCase):

    def setUp(self):
        self.test_db_path = "data/test_monitor.db"
        self.db = DatabaseManager(db_path=self.test_db_path)
        self.collector = SystemMetricsCollector()
        self.preprocessor = MetricsPreprocessor(window_size=20)
        self.detector = AIAnomalyDetector(contamination=0.05)
        self.alert_mgr = AlertManager(self.db, log_file="logs/test_health.log")

    def tearDown(self):
        # Clean up test database and log
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass

    def test_metrics_collection(self):
        """Test that psutil collects valid OS metrics."""
        metrics = self.collector.collect()
        self.assertIn("cpu", metrics)
        self.assertIn("memory", metrics)
        self.assertIn("disk", metrics)
        self.assertIn("processes", metrics)
        self.assertGreaterEqual(metrics["cpu"]["total_percent"], 0.0)
        self.assertGreaterEqual(metrics["memory"]["percent"], 0.0)
        self.assertGreaterEqual(metrics["processes"]["count"], 1)

    def test_database_persistence(self):
        """Test inserting and retrieving metric snapshots."""
        metrics = self.collector.collect()
        self.db.insert_metric(metrics)
        recent = self.db.get_recent_metrics(limit=5)
        self.assertEqual(len(recent), 1)
        self.assertIn("cpu_percent", recent[0])

    def test_preprocessor_baselines(self):
        """Test rolling baseline mean, std, and slope computation."""
        synthetic_history = [
            {
                "cpu_percent": 15.0 + i,
                "memory_percent": 40.0 + (i * 0.5),  # upward slope
                "swap_percent": 2.0,
                "disk_percent": 60.0,
                "disk_io_mb_sec": 5.0,
                "process_count": 200 + i,
            }
            for i in range(10)
        ]
        baselines = self.preprocessor.compute_baselines(synthetic_history)
        self.assertIn("cpu_percent", baselines)
        self.assertIn("memory_percent", baselines)
        # Memory had a strictly positive slope
        self.assertGreater(baselines["memory_percent"]["slope"], 0.0)
        # Check Z-Score calculation
        z = self.preprocessor.calculate_z_score(current_val=90.0, mean=45.0, std=10.0)
        self.assertEqual(z, 4.5)

    def test_ai_anomaly_detection_healthy(self):
        """Test AI engine under nominal conditions returns high health score."""
        nominal_metrics = self.collector.collect()
        nominal_metrics["cpu"]["total_percent"] = 15.0
        nominal_metrics["memory"]["percent"] = 45.0
        nominal_metrics["swap"]["percent"] = 5.0
        nominal_metrics["disk"]["percent"] = 50.0
        nominal_metrics["disk"]["io_total_mb_sec"] = 2.0
        nominal_metrics["processes"]["count"] = 180

        baselines = {
            "cpu_percent": {"mean": 15.0, "std": 3.0, "slope": 0.0},
            "memory_percent": {"mean": 45.0, "std": 2.0, "slope": 0.0},
            "disk_io_mb_sec": {"mean": 2.0, "std": 1.0, "slope": 0.0},
            "process_count": {"mean": 180.0, "std": 10.0, "slope": 0.0},
            "swap_percent": {"mean": 5.0, "std": 1.0, "slope": 0.0},
            "disk_percent": {"mean": 50.0, "std": 1.0, "slope": 0.0},
        }

        analysis = self.detector.analyze(nominal_metrics, baselines, [])
        self.assertGreaterEqual(analysis["health_score"], 80.0)
        self.assertEqual(analysis["health_status"], "Optimal")

    def test_ai_anomaly_detection_spike_and_leak(self):
        """Test AI engine catches severe CPU spike and memory leak slope."""
        stressed_metrics = self.collector.collect()
        stressed_metrics["cpu"]["total_percent"] = 96.0  # Spike
        stressed_metrics["memory"]["percent"] = 92.0

        baselines = {
            "cpu_percent": {"mean": 20.0, "std": 5.0, "slope": 0.0},
            "memory_percent": {"mean": 50.0, "std": 4.0, "slope": 0.35},  # Heavy upward slope
            "disk_io_mb_sec": {"mean": 5.0, "std": 2.0, "slope": 0.0},
            "process_count": {"mean": 200.0, "std": 10.0, "slope": 0.0},
            "swap_percent": {"mean": 5.0, "std": 1.0, "slope": 0.0},
            "disk_percent": {"mean": 50.0, "std": 1.0, "slope": 0.0},
        }

        # Provide a synthetic 15-sample history to trigger leak detection rule
        dummy_hist = [{"cpu_percent": 20.0, "memory_percent": 50.0 + i, "swap_percent": 5.0, "disk_percent": 50.0, "disk_io_mb_sec": 5.0, "process_count": 200} for i in range(15)]

        analysis = self.detector.analyze(stressed_metrics, baselines, dummy_hist)
        self.assertTrue(analysis["is_anomaly_detected"])
        self.assertLess(analysis["health_score"], 70.0)
        self.assertIn(analysis["health_status"], ["Degraded", "Critical Degradation"])

        # Verify alert manager produces alerts
        alerts = self.alert_mgr.process_anomalies(analysis["anomalies"], stressed_metrics)
        self.assertGreater(len(alerts), 0)


if __name__ == "__main__":
    unittest.main()
