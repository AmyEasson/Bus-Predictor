# Bus Delay Predictor (Hack the Burgh 2026)

Journey planner and delay map for Greater Manchester buses, built on the BODS live feed,
the BODS archive and the GTFS timetable.

## Setup
1. Clone this repository.
2. Open in VS Code.
3. When prompted, click **"Reopen in Container"** (or Command Palette `Cmd+Shift+P` / `Ctrl+Shift+P` ->
   `Dev Containers: Reopen in Container`). This installs `requirements.txt`.

Without the container: `pip install -r requirements.txt`, and `npm ci` in `frontend/`.

## Running
```bash
# backend (FastAPI) - http://localhost:8000, docs at /docs
cd backend && uvicorn app.main:app --reload --port 8000

# frontend (Vite + React) - http://localhost:5173
cd frontend && npm run dev
```
The frontend calls `http://localhost:8000` by default; set `VITE_API_URL` in `frontend/.env` to change it.

## Layout
| Path | What it is |
|---|---|
| `frontend/` | React + Leaflet app (journey planner tab, delay map tab) |
| `backend/app/` | FastAPI app. `routes.py` = real endpoints (stops, journeys, live buses); `mock_routes.py` + `mock_data.py` = placeholder delay endpoints in their final response shapes (`schemas.py`) |
| `data/` | GTFS timetable as parquet, `snapshot.sqlite` (live logger snapshot), `bods_logger.py` (the live logger) |
| `delay_engine/trip_matching/` | Live pipeline: `prepare_timetable.py` -> `matcher.py` -> `arrivals.py` -> `segments.py` |
| `delay_engine/archival_data/` | Archive pipeline: `archive_arrivals.py` -> `build_analysis.py` -> correlations, road works, route reliability, `current_delays.py` |

Each script's docstring has its usage line, including which directory to run it from.
Pipeline outputs go to `delay_engine/trip_matching/out/` (gitignored).

## Ports
- `5173`: Vite frontend
- `8000`: FastAPI backend
- `3000`, `8501`: forwarded by the dev container but unused
