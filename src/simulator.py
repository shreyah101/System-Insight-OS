"""
Workload & Stress Simulator Module
Provides safe, controlled synthetic workload generators for live Viva demonstrations and testing.
Simulates CPU spikes, memory leaks, and disk I/O bursts with automatic cleanup.
"""

import os
import time
import math
import tempfile
import threading
from typing import Dict, Any, List

class WorkloadSimulator:
    """Safe test harness to trigger anomalies during project demos and viva examinations."""

    def __init__(self):
        self._active_threads: List[threading.Thread] = []
        self._stop_events: List[threading.Event] = []
        self._allocated_memory_buffers: List[bytearray] = []
        self._lock = threading.Lock()

    def simulate_cpu_spike(self, duration_sec: int = 6) -> Dict[str, Any]:
        """Spawns lightweight math workers across cores to temporarily raise CPU usage."""
        stop_event = threading.Event()

        def cpu_worker():
            start = time.time()
            while not stop_event.is_set() and (time.time() - start) < duration_sec:
                # Math calculation to produce CPU load
                _ = [math.sqrt(i) * math.sin(i) for i in range(50000)]
                time.sleep(0.002)

        # Launch 2-4 worker threads depending on host cores
        worker_count = max(2, min(os.cpu_count() or 2, 4))
        for _ in range(worker_count):
            t = threading.Thread(target=cpu_worker, daemon=True)
            t.start()
            self._active_threads.append(t)

        self._stop_events.append(stop_event)
        return {
            "status": "started",
            "type": "CPU Spike",
            "duration": duration_sec,
            "message": f"Simulating high CPU load ({duration_sec}s) across {worker_count} threads."
        }

    def simulate_memory_leak(self, duration_sec: int = 8, chunks_mb: int = 60) -> Dict[str, Any]:
        """
        Simulates a gradual memory leak by allocating chunks of memory step-by-step
        to demonstrate the AI trend drift / slope detection. Automatically frees all RAM.
        """
        stop_event = threading.Event()

        def mem_worker():
            start = time.time()
            local_buffers = []
            try:
                while not stop_event.is_set() and (time.time() - start) < duration_sec:
                    # Allocate ~60MB chunk
                    chunk = bytearray(chunks_mb * 1024 * 1024)
                    # Touch pages so OS actually commits physical memory
                    for i in range(0, len(chunk), 4096):
                        chunk[i] = 1
                    local_buffers.append(chunk)
                    time.sleep(1.0)
            except MemoryError:
                pass
            finally:
                # Hold memory briefly then release safely
                time.sleep(1.5)
                del local_buffers

        t = threading.Thread(target=mem_worker, daemon=True)
        t.start()
        self._active_threads.append(t)
        self._stop_events.append(stop_event)

        return {
            "status": "started",
            "type": "Memory Leak",
            "duration": duration_sec,
            "message": f"Simulating memory leak (+{chunks_mb}MB/sec for {duration_sec}s). Auto-releases afterwards."
        }

    def simulate_disk_io(self, duration_sec: int = 5) -> Dict[str, Any]:
        """Performs rapid temporary file writes and reads to simulate heavy Disk I/O stress."""
        stop_event = threading.Event()

        def disk_worker():
            start = time.time()
            temp_files = []
            try:
                while not stop_event.is_set() and (time.time() - start) < duration_sec:
                    with tempfile.NamedTemporaryFile(delete=False) as f:
                        temp_files.append(f.name)
                        # Write 10MB in chunks
                        data = b"X" * (1024 * 1024)
                        for _ in range(10):
                            f.write(data)
                            f.flush()
                    time.sleep(0.1)
            finally:
                # Clean up temporary files
                for tf in temp_files:
                    try:
                        if os.path.exists(tf):
                            os.remove(tf)
                    except Exception:
                        pass

        t = threading.Thread(target=disk_worker, daemon=True)
        t.start()
        self._active_threads.append(t)
        self._stop_events.append(stop_event)

        return {
            "status": "started",
            "type": "Disk I/O Storm",
            "duration": duration_sec,
            "message": f"Simulating heavy disk I/O burst ({duration_sec}s) with auto-cleanup."
        }

    def stop_all(self):
        """Immediately stops all active simulated stressors."""
        for event in self._stop_events:
            event.set()
        self._stop_events.clear()
        self._active_threads.clear()
        self._allocated_memory_buffers.clear()
