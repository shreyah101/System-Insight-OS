/**
 * AI System Health Engine - Client-Side Controller
 * Subscribes to real-time SSE stream, manages Chart.js streaming, and handles viva simulation triggers.
 */

document.addEventListener("DOMContentLoaded", () => {
    // Current active chart metric view ('cpu', 'memory', 'disk_io')
    let currentChartMetric = "cpu";
    const maxChartPoints = 35;
    let knownAnomalyCount = 0;

    // DOM Elements
    const healthScoreNum = document.getElementById("healthScoreNum");
    const healthStatusBadge = document.getElementById("healthStatusBadge");
    const circularProgress = document.getElementById("circularProgress");
    const riskLevel = document.getElementById("riskLevel");
    const mlScoreVal = document.getElementById("mlScoreVal");
    const uptimeVal = document.getElementById("uptimeVal");
    const healthBanner = document.getElementById("healthBanner");
    const healthBannerText = document.getElementById("healthBannerText");

    // Metric Cards
    const cpuVal = document.getElementById("cpuVal");
    const cpuBar = document.getElementById("cpuBar");
    const cpuBaseline = document.getElementById("cpuBaseline");
    const cpuZScore = document.getElementById("cpuZScore");

    const memVal = document.getElementById("memVal");
    const memBar = document.getElementById("memBar");
    const memUsedLabel = document.getElementById("memUsedLabel");
    const memSlopeLabel = document.getElementById("memSlopeLabel");

    const diskVal = document.getElementById("diskVal");
    const diskBar = document.getElementById("diskBar");
    const diskIoVal = document.getElementById("diskIoVal");
    const diskFreeVal = document.getElementById("diskFreeVal");

    const procVal = document.getElementById("procVal");
    const procBar = document.getElementById("procBar");
    const swapVal = document.getElementById("swapVal");
    const netIoVal = document.getElementById("netIoVal");

    const anomalyCount = document.getElementById("anomalyCount");
    const anomalyList = document.getElementById("anomalyList");
    const processTableBody = document.getElementById("processTableBody");
    const toastContainer = document.getElementById("toastContainer");

    // Initialize Chart.js
    const ctx = document.getElementById("liveMetricsChart").getContext("2d");
    
    // Gradient backgrounds for datasets
    const gradientCurrent = ctx.createLinearGradient(0, 0, 0, 220);
    gradientCurrent.addColorStop(0, "rgba(6, 182, 212, 0.45)");
    gradientCurrent.addColorStop(1, "rgba(6, 182, 212, 0.0)");

    const gradientBaseline = ctx.createLinearGradient(0, 0, 0, 220);
    gradientBaseline.addColorStop(0, "rgba(139, 92, 246, 0.2)");
    gradientBaseline.addColorStop(1, "rgba(139, 92, 246, 0.0)");

    const chart = new Chart(ctx, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    label: "Live Utilisation",
                    data: [],
                    borderColor: "#06b6d4",
                    backgroundColor: gradientCurrent,
                    borderWidth: 2.5,
                    fill: true,
                    tension: 0.35,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                },
                {
                    label: "Baseline Normal (Mean)",
                    data: [],
                    borderColor: "#8b5cf6",
                    backgroundColor: gradientBaseline,
                    borderWidth: 1.8,
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.35,
                    pointRadius: 0,
                },
                {
                    label: "Upper Anomaly Threshold (+2.5σ)",
                    data: [],
                    borderColor: "rgba(244, 63, 94, 0.7)",
                    borderWidth: 1.5,
                    borderDash: [3, 3],
                    fill: false,
                    tension: 0.1,
                    pointRadius: 0,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 350 },
            interaction: {
                mode: "index",
                intersect: false,
            },
            plugins: {
                legend: {
                    position: "top",
                    labels: {
                        color: "#94a3b8",
                        font: { family: "'Plus Jakarta Sans', sans-serif", size: 11, weight: '600' },
                        boxWidth: 12,
                        padding: 15
                    }
                },
                tooltip: {
                    backgroundColor: "rgba(15, 23, 42, 0.95)",
                    titleColor: "#f8fafc",
                    bodyColor: "#cbd5e1",
                    borderColor: "rgba(255, 255, 255, 0.1)",
                    borderWidth: 1,
                    padding: 10,
                    boxPadding: 4,
                }
            },
            scales: {
                x: {
                    grid: { color: "rgba(255, 255, 255, 0.04)" },
                    ticks: {
                        color: "#64748b",
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        maxTicksLimit: 8
                    }
                },
                y: {
                    grid: { color: "rgba(255, 255, 255, 0.04)" },
                    ticks: {
                        color: "#64748b",
                        font: { family: "'JetBrains Mono', monospace", size: 10 }
                    },
                    beginAtZero: true,
                    suggestedMax: 100
                }
            }
        }
    });

    // Chart toggle view event listeners
    document.querySelectorAll(".chart-toggle-group .toggle-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".chart-toggle-group .toggle-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentChartMetric = btn.getAttribute("data-view");

            // Reset chart labels and data for clean transition
            chart.data.labels = [];
            chart.data.datasets.forEach(ds => ds.data = []);
            chart.update();

            // Adjust Y-axis scale based on metric
            if (currentChartMetric === "disk_io") {
                chart.options.scales.y.suggestedMax = 50;
                chart.data.datasets[0].label = "Disk I/O (MB/s)";
            } else {
                chart.options.scales.y.suggestedMax = 100;
                chart.data.datasets[0].label = currentChartMetric.toUpperCase() + " Utilisation (%)";
            }
        });
    });

    // Format Uptime
    function formatUptime(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        return `${h}h ${m}m ${s}s`;
    }

    // Toast Notification System
    function showToast(title, message, severity = "info") {
        const toast = document.createElement("div");
        toast.className = `toast toast-${severity.toLowerCase()}`;
        toast.innerHTML = `
            <div class="toast-content">
                <h4>${title}</h4>
                <p>${message}</p>
            </div>
        `;
        toastContainer.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateX(50px)";
            toast.style.transition = "all 0.3s ease";
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    }

    // Update Dashboard UI with latest state payload
    function updateDashboard(payload) {
        const { metrics, baselines, analysis } = payload;
        if (!metrics) return;

        // 1. Health Score & Status
        const score = analysis.health_score;
        healthScoreNum.textContent = score.toFixed(1);
        healthStatusBadge.textContent = analysis.health_status;
        healthStatusBadge.style.color = analysis.status_color;
        healthStatusBadge.style.borderColor = analysis.status_color;

        // Circular Gauge Conic Gradient
        const deg = (score / 100) * 360;
        circularProgress.style.background = `conic-gradient(${analysis.status_color} ${deg}deg, rgba(255, 255, 255, 0.05) 0deg)`;
        circularProgress.style.boxShadow = `0 0 30px ${analysis.status_color}40`;

        // Health Meta
        if (score >= 80) {
            riskLevel.textContent = "Minimal";
            riskLevel.style.color = "var(--color-optimal)";
            healthBanner.style.background = "rgba(16, 185, 129, 0.08)";
            healthBanner.style.borderColor = "rgba(16, 185, 129, 0.2)";
            healthBannerText.textContent = "All operating system metrics are operating within normal statistical baselines.";
        } else if (score >= 50) {
            riskLevel.textContent = "Moderate (Early Warning)";
            riskLevel.style.color = "var(--color-warning)";
            healthBanner.style.background = "rgba(245, 158, 11, 0.08)";
            healthBanner.style.borderColor = "rgba(245, 158, 11, 0.3)";
            healthBannerText.textContent = "Warning: Early performance degradation symptoms detected. Check anomalies below.";
        } else {
            riskLevel.textContent = "CRITICAL DEGRADATION";
            riskLevel.style.color = "var(--color-critical)";
            healthBanner.style.background = "rgba(244, 63, 94, 0.12)";
            healthBanner.style.borderColor = "rgba(244, 63, 94, 0.4)";
            healthBannerText.textContent = "Severe performance bottleneck or resource exhaustion in progress!";
        }

        mlScoreVal.textContent = `${analysis.ml_anomaly_score.toFixed(2)} (${analysis.ml_anomaly_score > 0.5 ? 'Anomaly' : 'Normal'})`;
        uptimeVal.textContent = formatUptime(metrics.uptime_seconds);

        // 2. Metric Cards
        // CPU
        const cpuP = metrics.cpu.total_percent;
        cpuVal.textContent = cpuP.toFixed(1);
        cpuBar.style.width = `${Math.min(cpuP, 100)}%`;
        if (baselines.cpu_percent) {
            cpuBaseline.textContent = `${baselines.cpu_percent.mean.toFixed(1)}%`;
            const z = ((cpuP - baselines.cpu_percent.mean) / baselines.cpu_percent.std).toFixed(1);
            cpuZScore.textContent = `${z > 0 ? '+' : ''}${z}σ`;
        }

        // RAM
        const memP = metrics.memory.percent;
        memVal.textContent = memP.toFixed(1);
        memBar.style.width = `${Math.min(memP, 100)}%`;
        memUsedLabel.textContent = `Used: ${metrics.memory.used_gb} / ${metrics.memory.total_gb} GB`;
        if (baselines.memory_percent) {
            const slope = baselines.memory_percent.slope;
            memSlopeLabel.textContent = `${slope > 0 ? '+' : ''}${slope.toFixed(2)}%/s`;
            memSlopeLabel.style.color = slope > 0.15 ? "var(--color-warning)" : "var(--text-primary)";
        }

        // Disk
        const diskP = metrics.disk.percent;
        diskVal.textContent = diskP.toFixed(1);
        diskBar.style.width = `${Math.min(diskP, 100)}%`;
        diskIoVal.textContent = `${metrics.disk.io_total_mb_sec.toFixed(1)} MB/s`;
        diskFreeVal.textContent = `${metrics.disk.free_gb} GB`;

        // Processes & Swap
        const procsCount = metrics.processes.count;
        procVal.textContent = procsCount;
        procBar.style.width = `${Math.min((procsCount / 400) * 100, 100)}%`;
        swapVal.textContent = `${metrics.swap.percent}%`;
        const totalNet = (metrics.network.recv_mb_sec + metrics.network.sent_mb_sec).toFixed(2);
        netIoVal.textContent = `${totalNet} MB/s`;

        // 3. Update Chart
        const timeLabel = metrics.iso_time.split(" ")[1];
        let currentVal = 0, meanVal = 0, stdVal = 1;

        if (currentChartMetric === "cpu") {
            currentVal = cpuP;
            if (baselines.cpu_percent) {
                meanVal = baselines.cpu_percent.mean;
                stdVal = baselines.cpu_percent.std;
            }
        } else if (currentChartMetric === "memory") {
            currentVal = memP;
            if (baselines.memory_percent) {
                meanVal = baselines.memory_percent.mean;
                stdVal = baselines.memory_percent.std;
            }
        } else if (currentChartMetric === "disk_io") {
            currentVal = metrics.disk.io_total_mb_sec;
            if (baselines.disk_io_mb_sec) {
                meanVal = baselines.disk_io_mb_sec.mean;
                stdVal = baselines.disk_io_mb_sec.std;
            }
        }

        const upperThreshold = Math.min(100, Math.max(meanVal + 2.5 * stdVal, meanVal + 10));

        chart.data.labels.push(timeLabel);
        chart.data.datasets[0].data.push(currentVal);
        chart.data.datasets[1].data.push(meanVal);
        chart.data.datasets[2].data.push(upperThreshold);

        if (chart.data.labels.length > maxChartPoints) {
            chart.data.labels.shift();
            chart.data.datasets.forEach(ds => ds.data.shift());
        }
        chart.update("none");

        // 4. Update Top Processes Table
        if (metrics.processes && metrics.processes.top) {
            renderProcesses(metrics.processes.top);
        }

        // 5. Check Anomalies & Alerts
        if (analysis.anomalies && analysis.anomalies.length > 0) {
            renderAnomalies(analysis.anomalies);
        }
    }

    // Render Processes Table
    function renderProcesses(processes) {
        processTableBody.innerHTML = processes.map(proc => `
            <tr>
                <td class="proc-pid">${proc.pid}</td>
                <td class="proc-name">${proc.name}</td>
                <td><strong style="color: ${proc.cpu_percent > 50 ? 'var(--color-warning)' : 'inherit'}">${proc.cpu_percent.toFixed(1)}%</strong></td>
                <td>${proc.memory_percent.toFixed(1)}%</td>
                <td><span class="status-pill">${proc.status}</span></td>
            </tr>
        `).join("");
    }

    // Render Anomalies in Feed
    function renderAnomalies(anomalies) {
        // Only re-render if count or items change
        const count = anomalies.length;
        anomalyCount.textContent = `${count} Active`;

        const html = anomalies.map(a => `
            <div class="anomaly-item ${a.severity.toLowerCase()}">
                <div class="anomaly-top">
                    <span class="anomaly-title">${a.severity}: ${a.metric_name}</span>
                    <span class="anomaly-time">${a.iso_time ? a.iso_time.split(" ")[1] : ''}</span>
                </div>
                <div class="anomaly-desc">${a.description}</div>
                <div class="anomaly-footer">
                    <span class="detector-badge">${a.detector}</span>
                    ${a.z_score !== null && a.z_score !== undefined ? `<span class="detector-badge">Z: ${a.z_score}σ</span>` : ''}
                </div>
            </div>
        `).join("");

        anomalyList.innerHTML = html;
    }

    // Fetch initial historical anomalies to populate on load
    fetch("/api/anomalies?limit=10")
        .then(res => res.json())
        .then(anomalies => {
            if (anomalies && anomalies.length > 0) {
                renderAnomalies(anomalies);
            }
        })
        .catch(err => console.error("Could not fetch anomalies:", err));

    // Connect to Server-Sent Events (SSE) Stream
    const eventSource = new EventSource("/api/stream");

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateDashboard(data);

            // Trigger Toast on new anomalies
            if (data.analysis && data.analysis.anomalies && data.analysis.anomalies.length > knownAnomalyCount) {
                const latest = data.analysis.anomalies[0];
                showToast(
                    `${latest.severity}: ${latest.metric_name}`,
                    latest.description,
                    latest.severity.toLowerCase()
                );
                knownAnomalyCount = data.analysis.anomalies.length;
            } else if (data.analysis && (!data.analysis.anomalies || data.analysis.anomalies.length === 0)) {
                knownAnomalyCount = 0;
            }
        } catch (err) {
            console.error("Error parsing SSE data:", err);
        }
    };

    eventSource.onerror = (err) => {
        console.warn("SSE connection lost. Reconnecting in background...", err);
    };

    // Viva Simulation Control Handlers
    document.getElementById("stressCpuBtn").addEventListener("click", () => {
        fetch("/api/simulate/cpu?duration=6", { method: "POST" })
            .then(res => res.json())
            .then(data => showToast("⚡ CPU Spike Stress Triggered", data.message, "warning"));
    });

    document.getElementById("stressMemBtn").addEventListener("click", () => {
        fetch("/api/simulate/memory?duration=8", { method: "POST" })
            .then(res => res.json())
            .then(data => showToast("💧 Memory Leak Stress Triggered", data.message, "warning"));
    });

    document.getElementById("stressIoBtn").addEventListener("click", () => {
        fetch("/api/simulate/disk?duration=5", { method: "POST" })
            .then(res => res.json())
            .then(data => showToast("💾 Disk I/O Storm Triggered", data.message, "warning"));
    });

    document.getElementById("stressStopBtn").addEventListener("click", () => {
        fetch("/api/simulate/stop", { method: "POST" })
            .then(res => res.json())
            .then(data => showToast("🛑 Stressors Terminated", data.message, "info"));
    });

    // Export CSV Report
    document.getElementById("exportBtn").addEventListener("click", () => {
        window.location.href = "/api/export";
    });
});
