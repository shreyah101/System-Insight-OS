"""
System Metric Collector Module
Uses psutil to collect real-time OS performance statistics.
"""

import os
import time
from typing import Dict, Any, List
import psutil


class SystemMetricsCollector:
    """Collects real-time OS hardware and process metrics using psutil."""

    def __init__(self):
        # Cache previous I/O counters to calculate rates per second
        self._last_time = time.time()
        self._last_disk_io = psutil.disk_io_counters()
        self._last_net_io = psutil.net_io_counters()

        # Warm-up CPU measurement (first call to cpu_percent with interval=None returns 0)
        psutil.cpu_percent(interval=None)

    def collect(self) -> Dict[str, Any]:
        """
        Collects comprehensive OS metrics snapshot.
        Returns a structured dictionary of metrics.
        """
        current_time = time.time()
        time_delta = max(current_time - self._last_time, 0.001)

        # 1. CPU Metrics
        cpu_total = psutil.cpu_percent(interval=None)
        cpu_cores = psutil.cpu_percent(interval=None, percpu=True)
        cpu_freq = psutil.cpu_freq()
        cpu_freq_current = round(cpu_freq.current, 1) if cpu_freq else 0.0

        # 2. Memory (RAM) Metrics
        vmem = psutil.virtual_memory()
        memory_total_gb = round(vmem.total / (1024 ** 3), 2)
        memory_used_gb = round(vmem.used / (1024 ** 3), 2)
        memory_avail_gb = round(vmem.available / (1024 ** 3), 2)
        memory_percent = vmem.percent

        # 3. Swap Memory Metrics
        swap = psutil.swap_memory()
        swap_total_gb = round(swap.total / (1024 ** 3), 2)
        swap_used_gb = round(swap.used / (1024 ** 3), 2)
        swap_percent = swap.percent

        # 4. Disk Usage Metrics (Primary Drive)
        try:
            # On Windows, os.path.abspath(os.sep) resolves to C:\
            primary_path = os.path.abspath(os.sep)
            disk = psutil.disk_usage(primary_path)
            disk_total_gb = round(disk.total / (1024 ** 3), 2)
            disk_used_gb = round(disk.used / (1024 ** 3), 2)
            disk_free_gb = round(disk.free / (1024 ** 3), 2)
            disk_percent = disk.percent
        except Exception:
            disk_total_gb, disk_used_gb, disk_free_gb, disk_percent = 0.0, 0.0, 0.0, 0.0

        # 5. Disk I/O Rates
        curr_disk_io = psutil.disk_io_counters()
        if curr_disk_io and self._last_disk_io:
            read_bytes_sec = max(0.0, (curr_disk_io.read_bytes - self._last_disk_io.read_bytes) / time_delta)
            write_bytes_sec = max(0.0, (curr_disk_io.write_bytes - self._last_disk_io.write_bytes) / time_delta)
            read_mb_sec = round(read_bytes_sec / (1024 ** 2), 2)
            write_mb_sec = round(write_bytes_sec / (1024 ** 2), 2)
            disk_io_total_mb_sec = round(read_mb_sec + write_mb_sec, 2)
        else:
            read_mb_sec, write_mb_sec, disk_io_total_mb_sec = 0.0, 0.0, 0.0
        self._last_disk_io = curr_disk_io

        # 6. Network I/O Rates
        curr_net_io = psutil.net_io_counters()
        if curr_net_io and self._last_net_io:
            net_recv_sec = max(0.0, (curr_net_io.bytes_recv - self._last_net_io.bytes_recv) / time_delta)
            net_sent_sec = max(0.0, (curr_net_io.bytes_sent - self._last_net_io.bytes_sent) / time_delta)
            net_recv_mb_sec = round(net_recv_sec / (1024 ** 2), 2)
            net_sent_mb_sec = round(net_sent_sec / (1024 ** 2), 2)
        else:
            net_recv_mb_sec, net_sent_mb_sec = 0.0, 0.0
        self._last_net_io = curr_net_io

        # 7. Process & Thread Statistics
        try:
            pids = psutil.pids()
            process_count = len(pids)
        except Exception:
            process_count = 0

        # Top 5 Resource-Consuming Processes
        top_processes = self._get_top_processes(limit=5)

        # 8. System uptime
        boot_time = psutil.boot_time()
        uptime_seconds = int(current_time - boot_time)

        self._last_time = current_time

        return {
            "timestamp": current_time,
            "iso_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time)),
            "cpu": {
                "total_percent": cpu_total,
                "cores_percent": cpu_cores,
                "freq_mhz": cpu_freq_current,
                "core_count": psutil.cpu_count(logical=True),
            },
            "memory": {
                "percent": memory_percent,
                "total_gb": memory_total_gb,
                "used_gb": memory_used_gb,
                "available_gb": memory_avail_gb,
            },
            "swap": {
                "percent": swap_percent,
                "total_gb": swap_total_gb,
                "used_gb": swap_used_gb,
            },
            "disk": {
                "percent": disk_percent,
                "total_gb": disk_total_gb,
                "used_gb": disk_used_gb,
                "free_gb": disk_free_gb,
                "read_mb_sec": read_mb_sec,
                "write_mb_sec": write_mb_sec,
                "io_total_mb_sec": disk_io_total_mb_sec,
            },
            "network": {
                "recv_mb_sec": net_recv_mb_sec,
                "sent_mb_sec": net_sent_mb_sec,
            },
            "processes": {
                "count": process_count,
                "top": top_processes,
            },
            "uptime_seconds": uptime_seconds,
        }

    def _get_top_processes(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieves top processes sorted by CPU and memory usage."""
        procs = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
            try:
                info = proc.info
                # Clean up None values
                cpu_p = info.get('cpu_percent') or 0.0
                mem_p = round(info.get('memory_percent') or 0.0, 2)
                procs.append({
                    "pid": info['pid'],
                    "name": info['name'] or "Unknown",
                    "cpu_percent": cpu_p,
                    "memory_percent": mem_p,
                    "status": info.get('status', 'running')
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # Sort primarily by memory + cpu impact
        procs.sort(key=lambda p: (p['cpu_percent'] + p['memory_percent']), reverse=True)
        return procs[:limit]
