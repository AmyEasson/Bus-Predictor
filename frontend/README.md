
# Bus Delay Predictor
### Hack the Burgh 2026

A bus journey planning and delay prediction application for Greater Manchester.

The project combines live bus data with timetable information to support journey planning and analyse bus service reliability.

## Features

### Journey Planning
- Search for bus journeys between stops.
- Find direct journeys and journeys requiring one transfer.
- Identify services operating on a selected travel date using GTFS timetable data.
- View departure times, arrival times, journey durations and interchange information.
- Inspect the stops served by each journey.

### Bus Delay Analysis
- Collect live bus location and timing data.
- Match observed bus runs to scheduled GTFS trips.
- Calculate actual stop arrival times using GPS observations.
- Calculate delays between consecutive stops.
- Aggregate segment-level delay statistics across services and time periods.

## Technology Stack

- **Backend:** Python, FastAPI, Pandas
- **Frontend:** React, Vite
- **Data:** Greater Manchester GTFS timetable data and BODS live bus data
- **Storage:** Parquet datasets and SQLite

## Setup

1. Clone this repository.
2. Open the project in VS Code.
3. When prompted, select **Reopen in Container**.

   Alternatively, open the Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`) and select `Dev Containers: Reopen in Container`.

## Running the Application

The backend and frontend must be started in separate terminals.

### 1. Backend

From the repository root, run:

```bash
PYTHONPATH=backend uvicorn app.main:app --reload
```

The FastAPI backend runs at:

`http://localhost:8000`

Interactive API documentation:

`http://localhost:8000/docs`

### 2. Frontend

Open a second terminal and navigate to the frontend directory (the directory containing `package.json`).

Start the Vite development server:

```bash
npm run dev -- --host
```

The terminal will display the local frontend address. Open that address in your browser.

## Data

The project uses GTFS timetable data stored as Parquet files in `data/`.

Live bus observations are collected from the BODS API and stored for subsequent processing and analysis.

Generated delay-analysis outputs are written to `out/`.

## Ports

| Port | Service |
|---|---|
| `3000` | React frontend (if configured) |
| `8000` | FastAPI backend |
| `8501` | Streamlit dashboard (if used) |
