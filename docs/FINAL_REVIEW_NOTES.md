# Final review notes

## Explain the project

**Objective.** Observe one computer's resource use, retain its recent history and explain unusual readings. The project adds local statistical context and incident records to a snapshot-style monitoring workflow. Existing OS tools also have useful history and diagnostics; this project does not claim they lack every historical feature.

**Telemetry.** psutil reads real OS counters for CPU, RAM, disk reads/writes, process count and swap. The first nonblocking CPU sample is discarded. Disk totals are cumulative, so we subtract successive totals and divide by the real monotonic interval. A reset or absent counter makes that interval unavailable.

**Why 60 samples?** At two seconds per measurement, sixty readings represent about two minutes of recent behaviour. This is small enough for a laboratory demonstration, but does not describe long-term daily patterns. Initial priming and unavailable intervals can extend warm-up.

**Warm-up.** We show real values immediately but wait for a complete historical window before issuing anomaly alerts. The new reading is evaluated before it enters history. This prevents the point being tested from shifting its own baseline.

**Z-Score.** Subtract the recent mean and divide by recent effective variation. A positive score means above baseline, negative below; absolute scores strictly greater than three flag. Per-unit minimum standard deviations handle nearly constant readings without division by zero.

**Isolation Forest.** Random trees isolate unusual combinations of supported resource inputs. We use sklearn's real implementation, one hundred trees, seed 42, contamination auto. It fits on historical data and returns an outlier flag and decision score. The score is not a probability of failure.

**Why two detectors?** Z is easy to inspect resource by resource. The forest examines combinations and a different view of normality. Both can be wrong; agreement raises investigation priority rather than proving a root cause.

**Severity.** Neither flag: NORMAL. Z only with largest absolute score up to four: LOW. Z only above four: MEDIUM. Forest only: HIGH. Both on the same reading: CRITICAL. These are the Review 2 rules, not severity inferred by a generative model.

**Alerts.** Anomalous samples are stored individually. They also update one continuing host-wide episode rather than creating a notification every two seconds. The episode records first/latest detection, peak severity, count and evidence. Five consecutive valid normal samples resolve it. Missing data and shutdown cannot prove recovery.

**Retraining.** After initial fitting we consider retraining every thirty eligible observations. Active episodes block it, and a flagged reading requires sixty consecutive clean valid readings before training can resume. This reduces learning an ongoing incident as normal. Z's rolling baseline still adapts and can miss slow drift.

**Persistence.** SQLite has sessions, metrics_history, alerts and workload_events. Each sample, episode update and heartbeat commits atomically. Structured JSON retains detailed evidence. Foreign keys link episodes to samples; indexed queries and WAL support separate dashboard readers.

**Streamlit updates.** One independent process collects. The UI reads SQLite using a timed fragment. It never starts a collector during refresh. An OS file lock prevents a second worker on the same database. Shutdown and stale-heartbeat states distinguish current from saved readings.

**OS connections.** Processor utilization reflects scheduling demand. RAM and swap relate to allocation and virtual memory. Disk rates describe storage demand. Process count reflects concurrency. Worker locks, monotonic scheduling, transactions and persistent files are OS concepts used by the implementation itself.

## What was delivered

Real collection, input validation, baseline mathematics, both detectors, severity classification, persistent episodes, an independent runtime, six dashboard pages, exports, synthetic replay, bounded workloads, local evaluation and automated tests are implemented.

Optional work remains: SMD/NAB public benchmarks, longer baseline models and broader platform validation. No seventy-minute experiment, public benchmark accuracy, leak diagnosis or crash-prediction claim is supplied.

## Before presenting

- [ ] Install dependencies and run `python -m pytest -q` on the presentation computer.
- [ ] Start one collector and one dashboard; choose a free local port.
- [ ] Verify the hostname and latest timestamp, then allow a full warm-up.
- [ ] Check all supported inputs, and explain any unavailable disk/swap values.
- [ ] Run one synthetic replay and clearly call it simulated.
- [ ] Show real history/export or its honest empty state.
- [ ] If using a local workload, review caps and explicitly confirm it.
- [ ] State that genuine workload intervals are not OS-failure labels.
- [ ] Keep the demonstration guide and actual test/verification report available.

See [VERIFICATION.md](VERIFICATION.md) for the measured verification run and its limits.
