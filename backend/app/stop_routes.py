"""Stop card endpoint: the stop, its lines, next departures and typical delay there."""
from fastapi import APIRouter, HTTPException, Query

from .services import delay
from .services.stop_info import get_stop_info

router = APIRouter(prefix="/api", tags=["stops"])


@router.get("/stops/{stop_id}")
def stop_info(stop_id: str, limit: int = Query(8, ge=1, le=30)):
    """Departures are for today from now (Europe/London); typical delay is for the current hour."""
    out = get_stop_info(stop_id, delay.now(), limit)
    if out is None:
        raise HTTPException(status_code=404, detail=f"Unknown stop: {stop_id}")
    return out
