# Verification

Verification date: **30 October 2026 (IST)**. Runtime checks were performed on Windows 11 with Python 3.13.7. These checks validate the implementation; they do not replace the planned local-machine evaluation study.

## Automated tests

The application suite contains **84 tests**, covering telemetry validation, elapsed-time disk rates, unavailable resources, rolling-window mathematics, detector boundaries, feature changes, retraining, incident recovery, SQLite integrity, worker lifecycle, IST conversion, dashboard controls and portable launch behavior.

The suite passed in both the existing development environment and a fresh virtual environment with downloaded dependencies. The final pre-publication run completed with **84 passed, 0 failed** in 28.85 seconds and **95% backend statement coverage** (835 statements, 45 uncovered). The fresh-environment run also passed all 84 tests in 25.45 seconds. Dependency consistency checks passed. `src/ui.py` is excluded from the backend coverage denominator and is checked through Streamlit AppTest and browser inspection.

Run the checks from an installed environment:

```bash
python -m compileall -q src scripts app.py run.py
python -m pip check
python -m pytest -q --cov=src --cov-report=term-missing
```

Use a writable temporary directory if the operating environment restricts pytest's default location. UI behavior is checked with Streamlit AppTest as well as browser inspection; backend statement coverage is not a measure of real-world anomaly-detection accuracy.

## Clean installation and launch

A source copy in a directory containing spaces started without a virtual environment or telemetry database. `python run.py --setup-only` created an isolated environment with `include-system-site-packages = false` and installed dependencies successfully. Fresh packages included Streamlit 1.66.1, pandas 3.1.0, NumPy 2.5.4 and scikit-learn 1.9.1.

The bootstrap was then launched from outside the project directory. The dashboard returned HTTP 200, genuine telemetry was stored in that installation's database, and recorded host metadata matched the local machine. A Windows interrupt stopped the bootstrap, launcher, collector and dashboard with exit code 0. The session was marked stopped and no owned child process remained running.

## Collection, persistence and recovery

- A 155-second collection run at the default two-second cadence persisted 78 readings, including 13 eligible decisions after counter priming, feature stabilization and the full 60-reading warm-up. The first-to-last saved duration was 153.61 seconds.
- All six signals were available on the verification machine. Readings were visible during warm-up and both detectors became ready afterward.
- A second collector for the same database was rejected. Opening two dashboard tabs left the collector count at one and created no extra monitoring sessions.
- Stopping and restarting collection retained the original records. CSV export included all 78 readings and their detector evidence.
- SQLite integrity checks returned `ok`; foreign-key checks returned no violations.
- Genuine statistical alert episodes were inspected, including episode continuation, priority escalation and recovery. Ordinary workstation activity can produce alerts; these observations are not evidence of OS failure.
- Deliberately terminating the verification worker caused the dashboard to show Stale data after the configured expiry. A restart retained history and marked the abandoned session interrupted rather than claiming recovery.

The short collection run measured a mean detection time of 5.65 ms, maximum detection time of 164.63 ms including initial fitting, mean collection-and-detection time of 17.21 ms, mean scheduling lateness of 7.95 ms, mean monitor-process CPU of 2.12%, and mean monitor RSS of 166.30 MiB. These are observations from a short, mostly warm-up run on one machine, not general performance guarantees. The timing excludes the final SQLite save transaction.

## Dashboard and evaluation checks

All six pages were inspected at desktop dimensions, with an additional narrow-screen layout check. Automated UI tests cover empty startup, resource selection, alert search, synthetic replay and simulation reset. Dashboard times, date axes, session selectors, evidence views and downloads use IST; persistence and raw CLI exports retain UTC.

Synthetic CPU, memory, disk, process and multivariate scenarios run through the actual detector engine without writing simulated samples into live history. Bounded workload controllers were tested with one-second durations and small limits, including cancellation, temporary-file/child-process cleanup and rejection of unsafe limits.

## Verification limits

- The planned 70-minute study has not been completed. No public benchmark score, real-world failure-detection accuracy or crash-prediction result is claimed.
- Windows runtime and shutdown behavior were exercised. Linux/macOS entry points and platform branches still need verification on those operating systems.
- SMD/NAB benchmarks remain optional and are not implemented.
- A hard-killed workload controller can leave an unfinished event or temporary directory. Normal completion and cancellation clean up; sleeping child processes have independent timeouts.
- Each demonstration computer needs its own dependency check, resource-availability check and full baseline warm-up.

See [EVALUATION.md](EVALUATION.md) for the study protocol and [DEMO_GUIDE.md](DEMO_GUIDE.md) for the presentation walkthrough.
