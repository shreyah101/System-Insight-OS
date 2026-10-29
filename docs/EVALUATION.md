# Evaluation protocol

The primary dataset is genuine telemetry from the demonstration machine. The application does not ship a completed 70-minute study and does not claim real-world accuracy from synthetic results.

## Local study

Plan one 30-minute ordinary-use session and four 10-minute scenario sessions. In each scenario, reserve three minutes for ordinary activity, a two-minute workload-demonstration window, then five minutes recovery. At two-second cadence this is about 2,100 scheduled readings across 70 minutes, before invalid intervals and initial warm-up.

The built-in demonstrations intentionally enforce short runs (20 seconds by default, never more than 60). Within the planned two-minute window, explicitly start bounded runs if appropriate. The event log records each actual interval separately; idle gaps must not be labelled as continuous workload. Do not silently lift safety limits to match a report's proposed duration. A warm-up starts afresh for each collector session.

Record ordinary use with:

```powershell
python -m scripts.collect_session --minutes 30 --export output/normal.csv
```

For a scenario, use `--minutes 10`, open the dashboard on that session, wait three minutes and explicitly start the intended workload from the lab page. Do not run two collectors for the same database. The dashboard supports selecting previous sessions and exporting full metrics; the CLI prints session IDs after recording.

Calculate a saved session report:

```powershell
python -m scripts.evaluate --session SESSION_ID --output output/session_evaluation.json
```

The report includes sample counts and actual first-to-last recorded duration, eligible readings, raw detector counts, sample-level TP/FP/FN/TN, precision/recall/F1, each workload's first-alert latency, missed intervals, five-clean-reading recovery time, episodes starting outside recorded workload intervals, and measured overhead. No hit produces a null latency and a missed interval, never a fabricated zero-second delay. An interval with no eligible readings is explicitly missed with zero eligible samples. Recovery is null when the observation period cannot establish it.

Labels represent known activity, not verified OS failure. Outside recorded workloads, normality is only presumed: unrecorded user work can cause alerts. The count of episodes starting outside workloads is a false-alert proxy, not adjudicated failure ground truth. In an ordinary-use study, manually review episodes before calling them false positives. Pending or unfinished workload events are disclosed and excluded from closed-interval scoring. Events without a real start are not workloads.

Warm-up/ineligible samples are excluded from sample metrics. For a compatible comparison, Z, forest and combined decisions use the same eligible rows. Combined prediction is the OR of detector flags; the severity distinguishes their agreement. No point adjustment expands a single hit into credit for a whole interval.

Monitor CPU is psutil process CPU percentage across the actual previous collection interval (one core at full utilization is 100%). RSS includes the Python/scientific runtime. Detection time measures preparation/fitting/scoring/explanation; collection-and-detection time also includes telemetry and state queries, but excludes the final SQLite commit. Sampling lateness measures deviation from the scheduled slot. Startup import cost occurs before the first cycle. These are observations, not promised overhead limits.

## Synthetic replay

```powershell
python -m scripts.evaluate --scenario "CPU spike" --output output/cpu.json
python -m scripts.evaluate --scenario "Memory growth" --output output/memory.json
python -m scripts.evaluate --scenario "Disk I/O spike" --output output/disk.json
python -m scripts.evaluate --scenario "Process increase" --output output/processes.json
python -m scripts.evaluate --scenario "Multivariate outlier" --output output/combined.json
python -m scripts.evaluate --scenario "Stable normal" --output output/normal_replay.json
```

The seed is fixed by central configuration. Each series is evaluated chronologically through the actual engine: historical warm-up, ordinary prelude, injected change, recovery. Original simulated timestamps and labels are kept. Results never enter the live SQLite tables. Reset clears only in-memory UI replay. A CLI report is explicitly tagged `source: synthetic`. Synthetic precision and recall measure these injected patterns; they do not measure prediction of computer failures.

The normal scenario can still generate statistical false positives because its random tails are not hard-bounded. Sustained or slowly increasing changes may be absorbed by the rolling statistical baseline. The forest can flag normal tail observations under `auto`. Report these effects openly.

## Optional public benchmarks

SMD and NAB were proposed in Review 2, but are optional future benchmarks and are not implemented or downloaded. If added, SMD needs a separate feature-index pipeline using official per-machine train/test splits; do not relabel arbitrary features as CPU/RAM. NAB needs original timestamps and single-series replay with official anomaly windows; do not join unrelated series into six-metric telemetry or assume two-second cadence. Select settings using training data only, then evaluate untouched test labels. Report point-level precision/recall/F1 without inflated interval credit.
