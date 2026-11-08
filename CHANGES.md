# Changelog

## Route ranking judged on arrival time (2026-11-08)

### Fixed

- **A slow route with no delay could be recommended over a fast one with a small delay.** For example, a 45-min route with no delay was "Most reliable" over a 13-min route expected 2 min late, even though the 13-min route arrives about 30 min earlier even on a bad day. Routes are now judged on **when you'd arrive on a bad day**: scheduled arrival plus bad-day delay (the model's P90, else the historical estimate). Tags (`routeRanking.js`):
  - **Best option:** earliest bad-day arrival. It's the recommendation, drawn solid on the map and highlighted, and the default sort.
  - **Most reliable:** the smallest bad-day delay, but only among routes arriving within 10 min of the best (`RELIABLE_WINDOW_MIN`), and only if steadier than the best. A long detour can't win it.
  - **Fastest on paper:** the shortest timetable, tagged only when it isn't the best option, i.e. it looks quickest but arrives later on a bad day. Only then does "Fast vs safe" appear (fastest on paper against the best option), with "Why the fastest-looking route is risky".
- **Checked on real searches.** North Manchester General → Lathbury Road at 11:00: the 34-min 156 › 118 is no longer promoted, because it arrives 12 min after the best option even on a bad day. Langham Road → Belfield Road at 17:00: Best 23 › 142 (17:47), Most reliable 371 › 42 (17:49, steadier), Fastest on paper 42 (17:51 on a bad day).

## Stops on the map, UI tidy-ups (2026-11-08)

- **Stop dots show direction of travel.** Each dot has an arrow pointing to the stop buses most often go to next, taken from the timetable (`bearing` in `describe_stop`; 15,300 stops have one, and the rest are only places where buses finish). The two "Belfield Road" stands point opposite ways (358° and 171°).
- **Picking a second stop on the map.**
  - With a stop card open, clicking another stop asks "Directions from [first stop] to here" or "View this stop". When the two stops share a name, the first stop's direction is added.
  - In directions, stop dots stay visible until a route is picked. Clicking one fills the empty box (From, then To); if both are filled it asks "Set as start" or "Set as destination".
  - Chosen stops are drawn red (place / destination) or filled blue (start).
- **Every bus stop shows on the map at street level (zoom 16+).** Stops are small white dots with a blue rim; hovering shows the name, direction and lines, and clicking opens the stop card. Only the stops in view are fetched, from the new `GET /api/stops-in-area?bbox=` (about 100 in the city centre, 0.03 s). That endpoint refuses areas larger than about 25 × 15 km and leaves out Metrolink stops, as search does. Stops aren't drawn in directions mode, to keep the route readable.
- **Road works layer:** only works in progress with an effect of 5 s or more per stretch are shown (152 of 1,214 at weekday 17:00). The route breakdowns still count planned works due by the travel date.
- **Removed:** the colour-by tabs on "What's slowing buses?" (the map always shows overall delay) and "View on delay map" on route cards (it did the same as "Route details").
- **Delay risk** explains itself on hover: how late you could be on a bad day (1 trip in 10). Low is under 5 min, Medium 5–10, High over 10.

**Memory note.** Each backend process uses about 2.4 GB once the timetable and model are loaded. On a 16 GB laptop with browsers open, two backends at once can trigger the kernel's out-of-memory killer, which is what stopped a test backend and a browser at 10:30.

## Road works in the app (2026-11-08)

Brings the road-works analysis (`archival_data/filter_roadworks.py`, `roadworks_flag.py`, `roadworks_explain.py`, `roadworks_by_hour.py`) into the app. Road works are known in advance from Street Manager permits, so they can inform delays before they happen.

### Data

- **`delay_engine/export_roadworks.py`** (also called by `export_for_api.py`) writes `roadworks.parquet`: 6,761 works that are in progress (1,163) or planned with a granted permit (5,598) and touch the carriageway. Each has its WGS84 position, street, traffic management, category and window, plus:
  - `measured_s`: extra delay per bus stretch measured while it was active (264 works seen by at least 50 bus passes)
  - `expected_s`: the typical extra for its traffic-management type, used when a work wasn't measured. Multi-way signals +19.1 s, two-way +6.9, road closure +5.0, lane closure +2.4 (each relative to the no-works mean of 4.3 s).

  It also writes `roadworks_effects.json` (the analysis tables). Permits run up to 31 Oct 2026, so "in progress" means as of then.

### Backend

- **`GET /api/roadworks?date=&hour=&bbox=`.** Works on at that moment, each with its effect scaled to the hour by the measured by-hour penalty (×1.33 at weekday 17:00, ×0.5 at 21:00), plus a summary of the analysis. About 1,200 works are active on a weekday; the response takes 0.14 s.
- **Route breakdowns** (`route_insight.py`) gain a **Road works** factor. It covers works within 75 m of a stretch ridden (the analysis radius) and active when the bus is there. One job adds its own effect; several at once add at least the "concurrent works" figure (+6.6 s for two, +12.1 s for three or more). Results are scaled to the hour. The route lists the works (`insight.roadworks`), and big ones feed the one-line reason.

### Frontend

- **Layers → Road works.** Every job on the road now (or at the delay layer's hour), as a marker sized and coloured by its effect on buses: big (≥15 s, mostly signals and closures), moderate or small. The tooltip shows type, street, status, dates and effect, and says "measured from N bus passes" or "typical for type".
- **"Road works" card.** Extra delay by traffic-management type (bars), "it adds up" (one, two or three-plus jobs at once), the weekday peak hour, the multiplier for the current hour, and the permit date. With both layers on, the cards stack in a scrolling area.
- **Route details.** A Road works factor card and a "Road works on this route" list with each job's effect; the works are marked on the chosen route.

### Fixed

- **Risk chips mixed two measures.** "Medium · 40%" sat next to "Low · 58%" because the label came from the model and the % from history. The chip now shows the model's label with its bad-day delay ("bad day: +5.4 min", one decimal, so 4.9 vs 5.1 doesn't look identical). The historical late share is on its own line ("In past data, 40% of these buses ran 5+ min late").
- **Route tags now follow the design.** Most reliable = lowest bad-day delay; Fastest on paper = shortest timetable; Balanced = earliest bad-day arrival. Before, "Most reliable" could carry a higher risk than a neighbour. The default sort is "Best arrival" (earliest arrival on a bad day); "Most reliable", "Fastest" and "Earliest" are also available. With the real model, Langham Road → Belfield Road at 17:00 Monday now shows a real trade-off: 42 direct (fastest) against 371 › 42 (most reliable).

## Real model connected, risk labels recalibrated (2026-11-08)

- **The real model** (`delay_engine/model/models/`, trained until 15 Oct on 1.6M examples, 96 routes) loads in the backend. `lightgbm` needs to be installed in the venv.
- **Its metadata confirms the input fix above matters.** "Late now" has importance 206; the next feature has 26. And on the model's own test set, "stays as late as it is now" scores 98 s error and "timetable / on time" 287 s, against the model's 81 s.
- **Risk labels** (`prediction.py`) now use P90 under 5 min = low, 5–10 = medium, over 10 = high. The 5 min matches the UK punctuality window. On 283 real planned journeys the old 3/6 cut-offs gave 70% medium and 6% low; the new ones give 57% low, 42% medium and 1% high.

## Realistic inputs for the delay model (2026-11-08)

Connects Amy's trained model (PR #10, `delay_engine/model/`) to the delay engine's history, so its predictions get realistic inputs.

### Why

The model predicts "how late will this bus be k stops ahead", given how late it is **now** plus recent route and network delays. For a planned journey the backend passed `delay_now_s = 0` (`ASSUMED_DELAY_NOW_S`) and nothing for the live features, so every prediction assumed the bus reaches your stop exactly on time in quiet traffic. That has two consequences:

- **The predictions are biased early.** Across 6.6M held-out bus arrivals (24 Oct–6 Nov, with typical values learnt from 27 Aug–23 Oct), the median bus is about 2 min late when you board.
- **The model's strongest input is fixed.** In a test, assuming on time gave identical predictions at 08:00 and 17:00.

Using each stop's typical lateness for that hour and day type instead cuts the error of that input from 4.3 to 3.6 min on average (18%), and from 7.0 to 5.6 min on weekdays 16:00–18:00 (19%).

### Changed

- **`backend/app/services/prediction.py`.** Each leg now gets realistic expected conditions instead of zeros:
  - `delay_now_s`: typical lateness of buses arriving at the boarding stop at that hour and day type, or the network average for the hour when the stop has no data
  - `recent_route_delay_s`: the route's median delay for that time band (route reliability)
  - `recent_added_delay_s`: the network's typical delay gained per stop at that hour

  These follow the same definitions as `features.add_live_features`. Each prediction now includes `assumed` (stop, minutes late assumed and its basis, one entry per leg), which the route details show: "Assumes your bus reaches Langham Road ~2 min late, as buses usually do there around 17:00."
- **`delay_engine/model/predict.py`.** `predict_arrival()` accepts `recent_route_delay_s` and `recent_added_delay_s` as values; previously only a raw `recent_arrivals` table could supply them. This is backward compatible: `recent_arrivals`, when given, still takes precedence.
- **`delay_engine/export_for_api.py`.** Writes `stop_typical.parquet` (per stop × day type × hour, n ≥ 10, 3 MB), and `added_med_s` in `network_hourly.parquet`.
- **`services/delay.py`.** New `expected_conditions()`.

### Not done

- **No trained model files on this machine.** The integration was checked end to end with a throwaway model in the same format, which proves the plumbing but not accuracy. The real `delay_engine/model/models/` (or `models_archive/`) is needed to see real predictions.
- **Risk thresholds** (since done, see below).
- **For trips leaving now,** the matched bus's live delay would beat a typical value. That needs a live feed.

## Delay insights back in the app (2026-11-08)

Brings the original design's delay features into the maps-style layout, backed by real data. The design's live weather ("light rain") and Christmas Markets aren't included: there's no live weather feed, and the events calendar only covers football and concerts.

### Backend

- **`services/route_insight.py`.** `/api/journeys` now adds `journey["insight"]` next to Amy's `journey["prediction"]`. For every stretch the journey rides, at its scheduled time and day type, it looks up the delay engine's stretch table and returns:
  - `stretches`: each coloured by typical lateness, for drawing the route
  - `typical_late_min`
  - `risk_pct`: the chance at least one leg's bus is more than 5 min late at that time of day, from `route_reliability_by_band.csv`, keyed by each leg's real `route_id`
  - `factors`: time of day; rain, using the network-wide measured effect because per-stretch estimates summed over a route are noise; and events, only when one is actually on near the route within its 2 h window
  - `worst`: the stretch where buses lose most time
  - a where/why `explanation`
  - `coverage` and `confidence`

  This adds about 0.05 s per search. A failure never breaks the journey list.

### Frontend

- **Route cards.** Each shows its tag (Most reliable / Balanced / Fastest on paper), arrival time, total minutes ("27 min · timetable 21 · +6 predicted"), lines, a delay-risk chip and bar with %, the reason, and "Route details" / "View on delay map". Ranking (`routeRanking.js`) uses the model's p90 when there is one and falls back to history, so routes are still ranked when the model isn't loaded. Sorting: most reliable, fastest or earliest.
- **Map.** Before a pick: most reliable drawn solid blue, fastest on paper dashed red, with a key. After a pick: the route coloured stretch by stretch by typical lateness (grey where there's no data), the alternative faded, and callouts for the slowest stretch and for what the reliable route avoids. The map frames routes clear of the panel.
- **Route details.** "Fast vs safe" comparison (only when the fastest and most reliable routes differ), "Why the fastest route is risky" / "What affects this route" factor cards with bars, the slowest stretch, data basis and confidence, Amy's model prediction, then the steps.
- **Explore.** Network figures for this hour, **Recent** trips (stored in the browser) with "Usually +6 min at 17:00", and a button to explore delays.
- **Delay layer card ("What's slowing buses?").** Colour by (Overall / Weather / Time / Events), factor switches with minutes, and the worst stretches at the selected hour; clicking one flies to it.

### Known issues

- **Some stops return no routes as a start.** Piccadilly Gardens stop `1800SB01681` gives no routes to anywhere tested (Didsbury, the airport, Belfield Road). It's probably a stand where buses finish. Users can't tell the city-centre stands apart, so stop search could group same-named stops nearby. This needs a change in `journey.py`.
- **Real fast-vs-safe trade-offs are rarer than in the mockups.** On most tested trips the most reliable route is also the fastest.
- **Journey search takes about 2.4 s**, mostly finding transfer journeys in `journey.py`.

## Maps-style app (2026-11-08)

The two tabs (Plan / Delay map) are replaced by one full-screen map with a maps-app flow. Amy's `feat/integrate-model` (journey delay predictions, ranking) was merged in first, and the new UI is built on her `PredictionBadge` and `JourneyRanking`.

### Flow

1. **Explore:** a floating "Search bus stops" box with a directions button, and a card with typical figures for this hour.
2. **Pick a stop:** the stop card shows its lines, which way it serves ("towards …"), typical lateness there now, the next timetabled departures, and **Directions** / **Start here**.
3. **Directions:** From and To boxes with a swap button; "Leave now / Depart at / Arrive by" with date and time. It searches as soon as both stops are set, and again when the time changes. Results are ranked by Amy's predictions ("Most reliable first" / "Earliest first") and show times, duration, line chips, the expected delay, the arrival time to plan around ("safe by"), and connection warnings.
4. **Pick a route:** a step-by-step timeline (board, ride N stops with the stops listed, change and wait, get off). The route is drawn on the map with the change stop marked.
5. **Layers button:** switches the delay hexagons on in any mode. A bottom bar then shows weekday/weekend, an hour-of-day timeline coloured by typical delay, the legend and the data window. The popover lists what was measured: weather, time of day and events.

### Backend

- **`GET /api/stops/{stop_id}`** (`stop_routes.py`, `services/stop_info.py`): the stop, its lines and direction, today's next departures from now, and typical lateness there at this hour (`delay.get_stop_typical`).
- **Stop search results now include `towards` and `lines`.** 86% of stop names are shared by several stops; Belfield Road alone is four different stops. These come from a per-stop summary built once from the timetable, which is loaded in the background at startup (`main.py` lifespan), so the first search is no longer about 4 s slow.

### Fixed

- **Map snapping back to the centre.** `BusMap`'s journey fit (from the merge) re-ran on every render, because `routePositions` is a new array each time, so the map jumped back whenever the app re-rendered. It's now keyed on the route's coordinates.
- **Typing over a selected stop.** The search box wiped what you typed: typing cleared the selection, and clearing the selection reset the text.
- **Suggestions cut off.** The floating panel no longer scrolls as a whole, which clipped the suggestion lists; each card scrolls its own content.

### Removed

- `Header.jsx`, `DelayPanel.jsx` and `DelayPanel.css` (the tabs and the old delay sidebar). The old sidebar card styles are removed from `index.css`. The colour-by and factor switches are gone from the UI; the API still supports them.

## Map visuals (2026-11-08)

- **Hexagons change size with zoom.** They range from 2 km across when zoomed out over the region to 150 m at street level (`hexSizeFor` in `App.jsx`; the allowed sizes are `HEX_SIZES` in `services/delay.py`). At zoom 14 and above, only the visible area is fetched. Each request takes under 0.2 s. They also have a lighter fill (30%) and an outline in their own colour, so the streets stay readable.
- **Weekday/weekend switch** on the delay panel. It defaults to today's day type. Without it, the map always showed today's pattern, and on a Sunday the afternoon shopping peak (13:00–14:00) looked like a missing rush hour.
- **Event pins.** They only appear from 2 h before an event to 2 h after it ends, the same window used to measure event effects, and only on today's day type. The event calendar (`events.csv`) ends on 9 Nov 2026.
- **Hexagons instead of stop-to-stop lines on the delay map.** The lines ran straight between stops (through buildings), because the timetable we have includes no road shapes. They also left gaps wherever our filters dropped a stretch. The map now draws hexagons 400 m across (`HEX_M` in `services/delay.py`). Each one is coloured by the bus-pass-weighted average delay over the stretches ending inside it, and is shown if it has at least 30 passes at that hour. Hovering shows the delay, the worst stretch inside the hexagon, the lines and the number of passes. All bands now share one style: 60% fill and a thin white outline.
- **API.** `/api/delay-map` returns `hexes` (about 3,500 on a weekday, 0.1 s, 1.3 MB) and `hex_m`. `limit` now only controls how many worst stretches are listed, and defaults to 20. Factor minutes are a bus-pass-weighted mean over every stretch at that hour.
- **Basemap.** Changed to the Stadia "Alidade Smooth" light grey tiles. They need no key on localhost; a deployed domain needs a free Stadia account. (CARTO Positron, which was tried first, now needs an API key.) Vector layers are drawn on a canvas.
- **Removed the bus position markers** and the 15-second polling behind them. They came from the logger snapshot, not live data. The header no longer claims "Live" and now says the data is from the past.

## Delay engine connected to the API (2026-11-08)

The delay map and network stats now show real numbers from 70 days of archive data (27 Aug to 6 Nov 2026: 37M stop arrivals and 25M stretch observations), instead of mock data. They are typical patterns for an hour and day type, not live data.

### Added

- **`delay_engine/export_for_api.py`.** Reduces the analysis tables to small files in `backend/data/delay/` (about 7 MB):
  - `segments.parquet`: about 277k rows covering 14.7k stretches, each by weekday/weekend and local hour. Each row has median lateness, median and p90 delay gained on the stretch, all-day lateness, rain and nearby-event effects, stop names and coordinates, and the route numbers using it.
  - `network_hourly.parquet`: per day type and hour, the % of buses on time, % more than 5 min late, mean delay, and how many buses are more than 5 min late on a typical day.
  - Copies of the route reliability CSVs, `current_delays.json` and `events.csv`.
  - `meta.json`: the data window and the network-wide factor effects from the correlation and roadworks tables.

  It runs in about 1 minute at 1.6 GB peak memory. It processes one day at a time and builds the medians in 8 slices of stretches, because a single query over all the data ran out of memory on a 16 GB laptop.
- **`backend/app/services/delay.py` and `delay_routes.py`.** Real versions of:
  - `/api/delay-map`. New optional parameters: `day_type`, `limit` (the worst N stretches, default 1500), `min_n` (default 20), `bbox`.
  - `/api/network/summary` and `/api/typical-delay`, both taking an optional `day_type`.
  - `/api/status`, which now reports `live: false` and the archive window.
  - New `/api/late-buses`, which serves the `current_delays.py` output.

  If the export files are missing, these endpoints return a 503 that says how to create them.

### Changed

- **Delay map meaning.** "Overall" is the stretch's typical all-day lateness, plus each enabled factor:
  - time of day: how much later or earlier buses are at the selected hour
  - weather: the measured rain effect, about 0
  - events: the measured effect of an event nearby, which only matters near venues

  Each factor's headline number is now the mean over the stretches shown, not the maximum, because a few noisy stretches dominated the maximum. The weather and events descriptions use the measured effects, and the event pins show events from `events.csv` for today.
- **Schemas** gained optional fields: `day_type`, `data_from`, `data_to` and `data_days` on `DelayMap`; `lines` and `observations` on `Segment`; `day_type` and `buses` on `NetworkSummary`. `Weather.temp_c` and `Weather.wind_kmh` can now be null, because there is no live weather feed.
- **Frontend.**
  - The planner's stats now show typical figures for the current hour, under the heading "Typical at this hour", instead of `–`.
  - The delay panel's "Sample data" warning is replaced with the data window.
  - The hour chart now covers 06:00–23:00 instead of 07:00–18:00.
  - Stretch tooltips show the lines using the stretch and how many bus passes the numbers come from.
- **Still mocked:** `/api/vehicles`, `/api/route` and `/api/places`. Journeys don't have predicted delays yet.

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
  - Integrates delay prediction information into journey cards, including predicted arrival times, delay risk levels and connection warnings.
  - Adds journey ranking and sorting, including most reliable and earliest departure options.

- **Journey map visualisation** (`BusMap.jsx`):
  - Draws the selected journey's route using its stop coordinates.
  - Displays markers for each stop along the journey.
  - Automatically adjusts the map viewport to fit the selected route.
  - Updates the route and map bounds when a different journey is selected.
  - Highlights origin, destination and interchange stops using distinct marker colours.
  - Displays stop information and arrival times in map popups.
  - Preserves live bus markers and stop hover previews when no journey is selected.

### Changed

- Updated the frontend journey result rendering to accommodate both direct and transfer journey response structures while preserving existing direct journey functionality.

## Historical bus-delay prediction (2026-11-08)

Adds a historical data pipeline and initial machine-learning model for predicting downstream bus delays using Greater Manchester BODS data.

### Added

- **Historical archive processing** (`delay_engine/model/process_archive.py`). Processes archived BODS data into weekly stop-arrival datasets for use in model training.
- **Archive-to-input conversion** (`delay_engine/trip_matching/archive_to_inputs.py`). Supports converting archived data into the inputs required by the trip-matching pipeline.
- **Streaming training-pair generation** (`delay_engine/model/build_pairs_streaming.py`). Builds downstream delay prediction examples from historical stop arrivals without loading the entire archive into memory.
- **Feature engineering** (`delay_engine/model/features.py`). Adds features covering:
  - Current bus delay, route, direction and destination stop.
  - Number of stops ahead and scheduled travel time.
  - Recent route delays, additional corridor delays and headway conditions.
  - Time of day, weekday/weekend and peak periods.
  - Weather, school terms, bank holidays and nearby events.
- **LightGBM quantile regression** (`delay_engine/model/train.py`). Trains P10, P50 and P90 models to estimate optimistic, typical and pessimistic downstream delays.
- **Prediction interface** (`delay_engine/model/predict.py`). Provides functionality for loading and using the trained models.
- **Exploration and evaluation** (`delay_engine/model/explore.py`). Supports analysis of the generated historical training data.

### Evaluation

- Generated approximately **2 million downstream prediction examples** from 227 days of historical BODS data.
- Implemented a chronological 80/20 train/test split, ensuring training targets were observed before the test period and excluding runs shared between training and testing.
- Compared model performance against timetable, current-delay and historical-median baselines.
- Initial P50 mean absolute error: **81.2 seconds**, approximately **17% better than the strongest baseline**.
- Added feature ablation, quantile calibration and feature-importance evaluation.

### Notes

- Raw BODS archives, generated Parquet datasets and locally trained model artefacts are not included in the source-code commit.
