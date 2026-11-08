# Changelog

## Repo cleanup (2026-11-08)

### Removed

- **`backend/engine/`.** It was a copy of `delay_engine/trip_matching/` (identical scripts and `out/` files) plus `compute_delays.py`. Nothing imported it. `delay_engine/` is now the only copy of the pipeline. `compute_delays.py` is gone with it: its clock-change handling was already ported into `arrivals.py`, and the file is still in git history.
- **`backend/app/models.py`**, which was empty.
- **Untracked root-level duplicates:** six GTFS parquets (byte-identical to `data/`), `snapshot_loop.py` (still in git history at `29c4043~1`) and `bods_logger.py` (moved over `data/bods_logger.py`, see below).

### Fixed

- **Bad first GPS fix (`arrivals.py`, `remove_jumps`).** Each fix was checked against the last kept one, starting from fix 0 unconditionally. A bad first fix therefore stayed in, and the good fixes after it were dropped until enough time passed for the jump to look possible: about 2 minutes of fixes for a 3 km error. Filtering now starts from the first fix that agrees with the one after it. `archive_arrivals.py` uses the same function, so it also benefits.
- **`archive_arrivals.py` couldn't import `arrivals.py`.** The two scripts are in different folders, so `from arrivals import ...` only worked with a manual `PYTHONPATH`. The script now adds `../trip_matching` to `sys.path` itself.
- **Usage lines pointed at deleted root files.** They now point at `data/`: `--gtfs-dir ../../data`, `--stops ../data/stops.parquet`, and so on. `archive_arrivals.py` now says to run it from `delay_engine/`, like the other archive scripts.
- **`/api/routes` returned made-up data on any error.** It now returns a 500 like the other endpoints.
- **`database.py`** no longer prints on import. It raises a clear error if `data/snapshot.sqlite` is missing, instead of letting `sqlite3` create an empty database at that path.
- **Misleading planner note.** "Delay predictions on: uses live bus positions, weather and local events" now says journeys show timetable times only, until the delay engine is connected.
- **Stale `current_delays.json`.** It was re-run with the same `as_of` (2026-10-29 07:45 UTC). The old file had explanations like "53 min late 0 min earlier" from before the 5-minute guard was added.

### Changed

- **`data/bods_logger.py`** now has the `_inside(r)` bounding-box helper, which was previously only in the root copy.
- **One API base URL for the frontend.** `api.js` exports `API_BASE_URL`, read from `VITE_API_URL` with `http://localhost:8000` as the default. `delayApi.js` now uses it and axios, instead of its own `fetch` and base URL. Note that `VITE_API_URL` no longer includes `/api`.
- **`.gitignore`.** Removed the `*.paraquet` typo, the meaningless `data/snapshot.sqlite/*.parquet` rule and the duplicate `__pycache__/`. Added `.vscode`, and grouped the rules with comments. Files that are already tracked (`data/snapshot.sqlite`, `trip_matching/out/*`) are unaffected by the ignore rules.
- **`requirements.txt`** adds `pyarrow`, `pyproj` and `scipy`, which the roadworks scripts use.
- **`README.md`** now has run commands for the backend and frontend, the correct frontend port (5173) and a map of the repo layout.

## Stop arrivals and segment delays (2026-11-07)

Adds steps 3 and 4 of the trip-matching pipeline: once runs are matched to timetable trips, work out when each bus reached each stop, then roll those up into per-segment delay stats.

### Added

- **`delay_engine/trip_matching/arrivals.py`** (step 3). For each run in `out/runs_matched.parquet`, reads its GPS fixes from the snapshot and the stops of its matched trip, and records a stop as reached when the bus's path comes within `--radius` m (default 50). The arrival time is interpolated along the closest segment between two fixes, so a stop the bus passes between two fixes still counts. Writes `out/stop_arrivals.parquet` with `delay_s = actual − scheduled`. Built-in cleaning, with counts printed at the end:
  - removes GPS jumps faster than `--max-speed` (35 m/s)
  - skips runs with fewer than `--min-fixes` fixes (5)
  - drops the first stop of every trip (buses waiting at the terminus look late)
  - drops arrivals interpolated across a fix gap over `--max-gap` (120 s)
  - drops arrivals earlier than the previous stop's arrival
  - drops delays outside `[--min-delay, --max-delay]` (−300 s to 3600 s)
- **`delay_engine/trip_matching/segments.py`** (step 4). Pairs up consecutive stops on each run that both have a clean arrival. For each pair it computes delay added, actual travel time and scheduled travel time. Results are grouped by `(from_stop, to_stop, time_band)` across all lines, plus a pooled `all` band. Time bands: weekday AM peak, interpeak, PM peak, off-peak, and weekend. Before grouping it drops:
  - pairs that add more than `--max-added` delay (600 s) or take longer than `--max-travel` (1800 s)
  - stops closer together than `--min-gap` (150 m)
  - pairs with less scheduled time than `--min-sched` (60 s), because the timetable's 1-minute resolution swamps them

  A segment is marked `reliable` once it has `--min-n` observations (5). Writes `out/segments.parquet` and `out/segments.csv`, and prints the 10 worst reliable segments.
- Generated outputs: `out/stop_arrivals.parquet`, `out/segments.parquet`, `out/segments.csv`.

### Fixed

- **Scheduled times on clock-change days (`arrivals.py`).** Scheduled arrivals were counted from local midnight, but GTFS counts them from local noon minus 12 h. That made every delay off by an hour on the two clock-change days a year. The new logic is the same as `service_day_start_utc` in `compute_delays.py`.
- **Stop pairing with gaps in `stop_sequence` (`segments.py`).** Adjacent stops were found by checking `stop_sequence + 1`. GTFS only guarantees that `stop_sequence` increases, so a feed numbered 1, 5, 10… would have produced no segments. `arrivals.py` now writes `stop_idx`, which is the stop's position in its trip (0, 1, 2…), and `segments.py` pairs on that instead. If `stop_arrivals.parquet` has no `stop_idx` column, `segments.py` stops and says to re-run `arrivals.py`.

## Code-review cleanup (2026-11-07)

### `delay_engine/trip_matching/prepare_timetable.py`

- **Extracted `_WEEKDAYS` constant.** The list of seven weekday names was written out twice inside `build_service_days`: once in the `for c in [...]` loop header and again as the `days` variable used in the `itertuples` loop body. Both now use a single module-level constant.
- **Added comment on `dep_s` column.** `build_trip_starts` reads `dep_s` from `stop_times.parquet`, which is not a standard GTFS column (standard GTFS uses `departure_time` as a string). The comment says this column is pre-processed, so anyone regenerating the parquet knows to include it. (`arrivals.py` relies on a similar pre-processed `arr_s` column.)
- **Added comment on `itertuples` loop performance.** The service-days expansion loop is O(services × date-range length). That is fine for typical GTFS feeds, and the comment flags it in case the calendar grows large.

### `delay_engine/trip_matching/matcher.py`

- **Added comment on discarded `pick()` result in pass 1.** Pass 1 keeps only runs with exactly one unique `trip_id`, so `pick()` can never return ambiguous rows there and the `_` discard is dead code. The comment explains this so it doesn't look like a bug.
- **Added comment on `tol=0` default for the exact pass.** A zero default allows no difference at all between the live aimed time and the timetable. The comment suggests raising it to about 60 s if pass-2 match rates look too low, since some feeds round aimed times to the minute.
- **Added comment on `unmatched_reason` loop.** The function uses a Python `for` loop over rows, which is slow at scale. The comment notes that it is diagnostic-only and runs once on the unmatched set, so the speed is acceptable.

### `bods_logger.py` (root-level copy)

- **Extracted `_inside(r)` predicate.** The bounding-box check (lat/lon not None and within the MIN/MAX bounds) was written identically in `in_box()` and inline in `poll_once()`. Both now call a shared `_inside(r)` helper. Note: this change is only in the root copy, not in the tracked `data/bods_logger.py`.


## Journey planning and transfer search (2026-11-08)

Adds timetable-based journey planning to the application, supporting both direct bus journeys and journeys involving one transfer.

### Added

- **`backend/app/services/journey.py`**. Implements timetable-based journey searches using the GTFS Parquet data:
  - Finds direct journeys between two bus stops.
  - Finds journeys involving one transfer between different bus routes.
  - Checks service calendars and calendar exceptions to ensure services operate on the selected date.
  - Calculates departure times, arrival times and total journey durations.
  - Includes the stops served by each journey, allowing routes to be displayed on the map.

- **Transfer journey search**. Introduces the following constraints:
  - Maximum of one transfer.
  - Minimum interchange wait of 5 minutes.
  - Maximum interchange wait of 30 minutes.
  - Maximum total journey duration of 120 minutes.
  - Excludes Metrolink stops.
  - Requires the connecting service to use a different bus route.
  - Removes duplicate results for the same pair of trips.

- **`/api/journeys` endpoint** (`backend/app/routes.py`). Exposes journey search through the FastAPI backend, accepting origin and destination stop IDs, a travel date, and optional departure/arrival time constraints. Supports including or excluding stop details in the response.

- **Frontend journey results** (`App.jsx`):
  - Displays direct and one-transfer journeys together.
  - Shows route numbers, departure and arrival times, and journey durations.
  - Distinguishes direct journeys from journeys requiring a change.
  - Displays the interchange stop and transfer waiting time.
  - Provides expandable journey-leg and stop information.
  - Supports selecting a journey for further inspection.

### Changed

- Updated the frontend journey result rendering to accommodate both direct and transfer journey response structures while preserving existing direct journey functionality.