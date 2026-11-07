# services/stops.py
from pathlib import Path
from functools import lru_cache
import pandas as pd

# Go from backend/app/services/ up to the project root
STOPS_PATH = Path(__file__).resolve().parents[3] / "data" / "stops.parquet"

@lru_cache(maxsize=1)
def load_stops():
    print(f"Loading stops from: {STOPS_PATH}")

    if not STOPS_PATH.exists():
        raise FileNotFoundError(f"stops.parquet not found at {STOPS_PATH}")

    df = pd.read_parquet(STOPS_PATH)

    df["stop_name"] = df["stop_name"].fillna("").astype(str)
    df["stop_id"] = df["stop_id"].fillna("").astype(str)

    return df

def search_bus_stops(search_term: str, limit: int = 10):
    stops = load_stops()

    # Filter out Metrolink tram stops safely
    if "stop_id" in stops.columns:
        stops = stops[~stops["stop_id"].str.startswith("9400ZZ", na=False)]

    # Find stops containing the search term
    matches = stops[
        stops["stop_name"].str.contains(
            search_term,
            case=False,
            na=False,
            regex=False
        )
    ].copy()

    if matches.empty:
        return []

    # Prioritize stops starting with the search term
    matches["priority"] = ~matches["stop_name"].str.lower().str.startswith(
        search_term.lower()
    )

    matches = matches.sort_values(
        ["priority", "stop_name"]
    ).head(limit)

    return matches[
        ["stop_id", "stop_name", "stop_lat", "stop_lon"]
    ].to_dict(orient="records")