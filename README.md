# AI-Based System Health Monitoring Engine for Early Detection of OS Performance Degradation

A real-time, AI-driven operating system health monitoring engine designed to detect early degradation symptoms—such as memory leaks, CPU spikes, disk thrashing, and process exhaustion—before performance collapses.

---

##  Key Features

1. **Continuous Real-Time Data Collection (`psutil`)**
   - **CPU**: Overall utilization, per-core metrics, frequency, and core counts.
   - **RAM (Memory)**: Used %, available GB, total physical memory.
   - **Swap Memory**: Swap consumption and paging pressure.
   - **Disk**: Storage fullness %, free GB, and real-time Disk I/O throughput (MB/s).
   - **Network**: Combined upload and download transfer rates (MB/s).
   - **Process Monitor**: Total running process count and top resource-consuming processes ranked by CPU and RAM impact.

2. **Statistical Baseline & Trend Analysis**
   - Computes rolling statistical baselines (Mean, Standard Deviation).
   - Calculates **Linear Regression Slope ($d(RAM)/dt$)** to detect sustained upward memory climbs characteristic of slow-burn **memory leaks**.

3. **Hybrid AI Anomaly Detection Engine**
   - **Isolation Forest (Machine Learning)**: Unsupervised model that evaluates multi-variate feature vectors across all system dimensions to flag anomalous system states.
   - **Z-Score Normalization**: Identifies rapid metric deviations ($|Z| > 2.5\sigma$ warning, $|Z| > 3.5\sigma$ critical).
   - **Degradation Predictor**: Forecasts time-to-exhaustion (e.g. *"RAM exhaustion predicted in ~14 minutes"*).
   - **Composite Health Score (0 - 100)**: Dynamic health score reflecting system stability and degradation risk.

4. **Multi-Channel Alert & Logging Module**
   - Graded severity triaging: `HEALTHY`, `INFO`, `WARNING`, `CRITICAL`.
   - Debounced alerts stored persistently in **SQLite (`data/health_monitor.db`)** and file logs (`logs/system_health.log`).
   - Actionable recommendations (e.g., specific high-load process PID and suggested remedy).

5. **Viva Demo Panel & Stress Simulator**
   - Built-in safe synthetic workload triggers for live viva evaluation:
     -  **CPU Spike**: Controlled multi-core workload.
     -  **Memory Leak**: Stepwise allocation with auto-cleanup.
     -  **Disk I/O Storm**: Rapid temporary disk writes and removals.
     -  **Kill Switch**: Immediate stressor termination.

6. **Dual Interactive Dashboards**
   - **Flask Real-Time Dashboard**: Modern dark-mode glassmorphic interface with Server-Sent Events (SSE) 1-second dynamic streaming, Chart.js graphs, health gauge, and toast alerts.
   - **Streamlit Dashboard**: Complementary data science dashboard (`app_streamlit.py`).

---

## System Architecture

```
+-------------------------------------------------------------+
|                      Operating System                       |
|        (CPU, RAM, Swap, Disk, Disk I/O, Processes)          |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|             Data Collection Module (psutil)                 |
|                   [src/collector.py]                        |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|             Data Processing & Storage (SQLite)              |
|        [src/database.py] & [src/preprocessor.py]            |
|         (Rolling Baseline: Moving Avg, Std, Slope)          |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|                 Hybrid AI Anomaly Engine                    |
|                   [src/ai_engine.py]                        |
|       - Isolation Forest (Unsupervised ML)                  |
|       - Z-Score Statistical Dynamic Thresholds              |
|       - Memory Leak / Trend Drift Slope Detection           |
|       - Composite Health Score (0 - 100)                    |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|                 Alert & Logging Module                      |
|                 [src/alert_manager.py]                      |
|         (logs/system_health.log & health_monitor.db)        |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|                     User Dashboards                         |
|   1. Flask Glassmorphic Web App (app.py)                    |
|   2. Streamlit Dashboard (app_streamlit.py)                 |
+-------------------------------------------------------------+
```

---

##  Quick Start Guide

### 1. Activate Virtual Environment
```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

### 2. Option A: Run the Flask Web Dashboard (Recommended)
```powershell
python app.py
```
Open your browser at: **[http://localhost:5000](http://localhost:5000)**

### 3. Option B: Run the Streamlit Dashboard
```powershell
streamlit run app_streamlit.py
```
Open your browser at: **[http://localhost:8501](http://localhost:8501)**

---

##  Running Automated Tests

Run the test suite to verify metric collection, baseline computation, Isolation Forest inference, and SQLite persistence:
```powershell
python -m unittest tests/test_engine.py
```

---

##  Project Structure

```
project/
├── src/
│   ├── __init__.py
│   ├── collector.py        # psutil real-time metrics extraction
│   ├── database.py         # SQLite schema & persistence
│   ├── preprocessor.py     # Rolling baselines, std, trend slopes
│   ├── ai_engine.py        # Isolation Forest + Z-Score + Drift Engine
│   ├── alert_manager.py    # Multi-level alerts, logging, debouncing
│   └── simulator.py        # Safe stress workload generators for viva
├── templates/
│   └── index.html          # Modern glassmorphic dashboard HTML
├── static/
│   ├── css/style.css       # Premium responsive design system
│   └── js/dashboard.js     # SSE stream & Chart.js real-time charts
├── tests/
│   └── test_engine.py      # Automated unit tests
├── data/                   # SQLite database directory (health_monitor.db)
├── logs/                   # System health log files (system_health.log)
├── app.py                  # Flask server with real-time SSE stream
├── app_streamlit.py        # Streamlit alternative dashboard
├── requirements.txt        # Frozen dependencies
├── VIVA_GUIDE.md           # Complete viva speech & question bank
└── README.md               # Project documentation
```
