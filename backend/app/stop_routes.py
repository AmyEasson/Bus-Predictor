"""Stop card endpoint: the stop, its lines, next departures and typical delay there."""
from fastapi import APIRouter, HTTPException, Query

from .services import delay
from .services.stop_info import describe_stop, get_stop_info
from .services.stops import load_stops

router = APIRouter(prefix="/api", tags=["stops"])


@router.get("/stops-in-area")
def stops_in_area(bbox: str = Query(..., description="min_lat,min_lon,max_lat,max_lon"),
                  limit: int = Query(1500, ge=1, le=5000)):
    """Bus stops inside a map area (for drawing stops when zoomed in). Metrolink stops are left out, as in search."""
    try:
        lat0, lon0, lat1, lon1 = (float(v) for v in bbox.split(","))
    except ValueError:
        raise HTTPException(status_code=422, detail="bbox must be min_lat,min_lon,max_lat,max_lon")
    if (lat1 - lat0) * (lon1 - lon0) > 0.05:  # roughly 25 km x 15 km: zoomed out too far to be useful
        raise HTTPException(status_code=422, detail="Area too large: zoom in to see stops")
    s = load_stops()
    s = s[s.stop_lat.between(lat0, lat1) & s.stop_lon.between(lon0, lon1) & ~s.stop_id.str.startswith("940")]
    s = s.head(limit)
    out = []
    for r in s.itertuples(index=False):
        d = describe_stop(r.stop_id)
        out.append({"stop_id": r.stop_id, "stop_name": r.stop_name, "stop_lat": float(r.stop_lat),
                    "stop_lon": float(r.stop_lon), "towards": d["towards"], "lines": d["lines"][:6],
                    "bearing": d["bearing"]})
    return out


@router.get("/stops/{stop_id}")
def stop_info(stop_id: str, limit: int = Query(8, ge=1, le=30)):
    """Departures are for today from now (Europe/London); typical delay is for the current hour."""
    out = get_stop_info(stop_id, delay.now(), limit)
    if out is None:
        raise HTTPException(status_code=404, detail=f"Unknown stop: {stop_id}")
    return out
