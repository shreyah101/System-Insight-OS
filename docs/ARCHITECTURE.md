# Architecture

The independent collector process owns telemetry and model state. Each dashboard is a reader. SQLite is the durable boundary, so closing a browser has no effect on sampling and opening a second tab creates no extra collectors.

## One cycle

1. Read psutil counters with a timezone-aware wall timestamp and monotonic elapsed interval.
2. Validate each signal independently. Reject nonfinite/negative readings and percentages outside 0–100. Missing inputs remain unavailable.
3. Choose the stable ordered supported feature schema. Five repeated availability changes restart warm-up unless an episode is active.
4. Read statistics from the historical deque. Require a complete 60-row eligible window before scoring.
5. Fit if allowed, using historical rows only. Independently score Z and forest on the same new input.
6. Combine flags into the exact five priority levels. Generate evidence-based prose without a root-cause claim.
7. Commit sample evidence, episode changes and heartbeat in one SQLite transaction.
8. Publish through that commit, then append the valid input to the bounded in-memory history.

A failed commit does not append the input. Model fitting may have occurred, but it used the same committed historical window. Error state is persisted when possible; a full database outage becomes stale to the UI. SQLite retries contention through its five-second busy timeout; the next cycle retries after a failure.

## Modules

`models` supplies dataclasses, metric order and severity. `config` validates the central YAML file. `telemetry` performs read-only host inspection and counter-to-rate conversion. `detection` holds rolling statistics, actual sklearn models, feature stability and training suspension. `storage` handles schema, bounded/indexed queries, exports and stateless transactional episode updates. `runtime` handles locks, signals, deadlines and stale states. `ui` renders six database-backed pages. `evaluation` reuses the detection engine chronologically; `workloads` owns only its explicitly spawned demonstration resources.

## Concurrency and lifecycle

The worker takes an advisory byte lock on Windows (`msvcrt`) or file lock on POSIX (`flock`) beside the canonical database path. The lock is held until shutdown and released by the OS after a crash. These are local-file locks: use a local database, not a network share or aliases/hardlinks to the same database. Separate database paths deliberately support isolated runs.

The worker waits on an interruptible Event between deadlines. It uses monotonic time, skips missed slots and never sends catch-up bursts. SIGINT/SIGTERM and Windows SIGBREAK request shutdown. A completed cycle finishes atomically. The launcher asks both owned children to stop and uses termination only after a timeout.

Each query/transaction opens and closes its own connection. WAL allows concurrent readers; transactions retain foreign-key integrity. The dashboard never calls telemetry collection. Optional process inspection is a separate read-only snapshot, explicitly requested through a button.

## Episodes and unavailable inputs

There is at most one active host-wide episode per session. Every eligible anomalous row continues it until five consecutive eligible normal samples resolve it. Peak priority is monotonic within the episode. First/latest sample foreign keys point to detected observations. The union of detector flags is episode-wide and must not be interpreted as both flagging its latest sample. Latest evidence stores the exact detector outputs.

Any missing active feature pauses the combined decision and breaks the clean streak. Persistently unsupported metrics are omitted from a newly fitted schema, never zero-filled. During an active incident, the existing schema/model is frozen; permanently lost inputs require a fresh session rather than declaring an unobserved recovery. A prior active episode remains unresolved after shutdown or interruption.

## Scientific boundaries

Population standard deviation (`ddof=0`) plus per-unit floors defines Z and the chart band. No normal-distribution confidence coverage is claimed. The statistical baseline continues rolling during an incident; this can adapt away slow changes. Forest training is blocked until incident resolution and a 60-reading clean streak. No detector score is a calibrated failure risk. A training distribution with entirely constant features can leave Isolation Forest insensitive; Z still provides a separate check.
