from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from . import mock_data
from .schemas import (
    RouteRequest,
    RouteResponse,
    Stop,
    Vehicle,
)

# Still mocked: /places (superseded by /stops/search), /vehicles, /route.
# The delay endpoints now live in delay_routes.py and read real data.
router = APIRouter()


def _hour(hour: int | None) -> int:
    return hour if hour is not None else mock_data.now().hour


def _require_stop(stop_id: str):
    if mock_data.get_stop(stop_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown stop: {stop_id}")


@router.get("/places", response_model=list[Stop])
def places(q: str | None = None):
    return mock_data.get_places(q)


@router.get("/vehicles", response_model=list[Vehicle])
def vehicles(hour: int | None = Query(None, ge=0, le=23)):
    return mock_data.get_vehicles(_hour(hour))


@router.post("/route", response_model=RouteResponse)
def route(req: RouteRequest):
    _require_stop(req.origin_id)
    _require_stop(req.destination_id)
    if req.origin_id == req.destination_id:
        raise HTTPException(status_code=400, detail="Origin and destination must differ")
    return mock_data.get_route_response(req.origin_id, req.destination_id, req.mode, req.time)
