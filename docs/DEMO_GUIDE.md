# Five-minute faculty demonstration

Before the review, install requirements and launch `python -m scripts.launch`. Allow the collector to warm up with ordinary activity. Do not run a workload during warm-up. Keep the actual session selected and verify the last sample timestamp advances. If a port is occupied, launch the worker and Streamlit separately on a free port.

1. **0:00–1:00 — Real OS signals.** Open Overview. Explain CPU scheduling demand, physical memory, swap, disk rates and existing process count. Point out the host metadata, recorded uptime and latest timestamp. Emphasize that the numbers come from psutil and SQLite.
2. **1:00–2:00 — Historical context.** Open Resource explorer, switch CPU to disk write, and change the time filter. Explain counter delta divided by actual elapsed seconds. Show the previous-window mean and effective-standard-deviation band. Missing readings are unavailable, not zero.
3. **2:00–3:00 — Two complementary detectors.** Open Anomaly detection. Explain signed Z, the strict three-sigma rule and the forest score. Walk through LOW/MEDIUM/HIGH/CRITICAL. Priority is an investigation aid, not proof of failure.
4. **3:00–4:00 — Guaranteed reproducible example.** Open Evaluation & demo lab → Synthetic replay. Run CPU spike or Multivariate outlier. Show the SIMULATED label, scored chart, warm-up exclusion and measured detector results. A false positive or missed synthetic point is a result to discuss, not hide. Reset the simulation to prove it is a separate browser workflow.
5. **4:00–5:00 — Persistence and limitations.** Open Alert history. If a genuine episode exists, inspect first/latest times, peak severity and baseline evidence. Otherwise explain the honest empty state; do not pretend synthetic episodes are live. Prepare/download the telemetry CSV. Stop the collector with Ctrl+C, observe Offline and retained history, then restart and show a new session. End with the limitation: slow drift and legitimate heavy work can challenge both models.

Optional live demonstration: after warm-up, review the visible caps, tick confirmation and start one short bounded workload. Cancel it and show its actual timestamps. It may be too small to cause an alert. Never promise a critical alert from a small load or raise caps to manufacture one.

Bring [FINAL_REVIEW_NOTES.md](FINAL_REVIEW_NOTES.md) for concise answers and [EVALUATION.md](EVALUATION.md) for the study plan. The automated test suite also verifies detector/episode behavior without requiring unsafe live loads.
