"""Delay endpoints backed by the delay engine's exported tables (see services/delay.py)."""
from fastapi import APIRouter, HTTPException, Query

from .schemas import ColourBy, DayType, DelayMap, NetworkSummary, Status, TypicalDelay
from .services import delay

router = APIRouter(prefix="/api", tags=["delays"])
VALID_FACTORS = set(delay.ALL_KEYS)


def _hour(hour: int | None) -> int:
    return hour if hour is not None else delay.now().hour


def _bbox(bbox: str | None):
    if bbox is None:
        return None
    try:
        vals = [float(v) for v in bbox.split(",")]
    except ValueError:
        vals = []
    if len(vals) != 4:
        raise HTTPException(status_code=422, detail="bbox must be min_lat,min_lon,max_lat,max_lon")
    return vals


def _data(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except delay.DelayDataMissing as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/status", response_model=Status)
def status():
    return _data(delay.get_status)


@router.get("/delay-map", response_model=DelayMap)
def delay_map(
    hour: int | None = Query(None, ge=0, le=23),
    colour_by: ColourBy = "overall",
    factors: str = "weather,time_of_day,events",
    day_type: DayType | None = Query(None, description="default: today's"),
    limit: int = Query(20, ge=0, le=10000, description="worst N stretches to list (hexagons always cover all)"),
    min_n: int = Query(20, ge=1, description="bus passes needed before a stretch is shown"),
    bbox: str | None = Query(None, description="min_lat,min_lon,max_lat,max_lon"),
    hex_m: int = Query(delay.HEX_M, description=f"hexagon width in metres, one of {delay.HEX_SIZES}"),
):
    if hex_m not in delay.HEX_SIZES:
        raise HTTPException(status_code=422, detail=f"hex_m must be one of {list(delay.HEX_SIZES)}")
    enabled = [f for f in factors.split(",") if f]
    unknown = set(enabled) - VALID_FACTORS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown factors: {sorted(unknown)}")
    return _data(delay.get_delay_map, _hour(hour), colour_by, enabled, day_type=day_type,
                 limit=limit, min_n=min_n, bbox=_bbox(bbox), hex_m=hex_m)


@router.get("/network/summary", response_model=NetworkSummary)
def network_summary(hour: int | None = Query(None, ge=0, le=23), day_type: DayType | None = None):
    return _data(delay.get_network_summary, _hour(hour), day_type)


@router.get("/typical-delay", response_model=TypicalDelay)
def typical_delay(from_id: str, to_id: str, hour: int | None = Query(None, ge=0, le=23),
                  day_type: DayType | None = None):
    out = _data(delay.get_typical_delay, from_id, to_id, _hour(hour), day_type)
    if out is None:
        raise HTTPException(status_code=404, detail="No data for that stretch at that hour "
                                                    "(stops must be adjacent on a route)")
    return out


@router.get("/roadworks")
def roadworks(
    day: str | None = Query(None, alias="date", description="YYYY-MM-DD, default today"),
    hour: int | None = Query(None, ge=0, le=23),
    bbox: str | None = Query(None, description="min_lat,min_lon,max_lat,max_lon"),
):
    """Road works on at that date/hour, with the extra delay per bus stretch to expect (measured for works the
    analysis saw, else typical for the traffic-management type), and the analysis summary."""
    from datetime import date as _date
    try:
        d = _date.fromisoformat(day) if day else delay.now().date()
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    return _data(delay.get_roadworks, d, _hour(hour), _bbox(bbox))


@router.get("/late-buses")
def late_buses():
    """Buses running late at one moment and why (current_delays.py output; a replayed past moment, see as_of_utc)."""
    return _data(delay.get_late_buses)
