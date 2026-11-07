from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from . import mock_data
from .schemas import (
    ColourBy,
    DelayMap,
    NetworkSummary,
    RouteRequest,
    RouteResponse,
    Status,
    Stop,
    TypicalDelay,
    Vehicle,
)

router = APIRouter()

VALID_FACTORS = set(mock_data.ALL_KEYS)


def _hour(hour: int | None) -> int:
    return hour if hour is not None else mock_data.now().hour


def _require_stop(stop_id: str):
    if mock_data.get_stop(stop_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown stop: {stop_id}")


@router.get("/status", response_model=Status)
def status():
    return mock_data.get_status()


@router.get("/places", response_model=list[Stop])
def places(q: str | None = None):
    return mock_data.get_places(q)


@router.get("/network/summary", response_model=NetworkSummary)
def network_summary(hour: int | None = Query(None, ge=0, le=23)):
    return mock_data.get_network_summary(_hour(hour))


@router.get("/vehicles", response_model=list[Vehicle])
def vehicles(hour: int | None = Query(None, ge=0, le=23)):
    return mock_data.get_vehicles(_hour(hour))


@router.get("/delay-map", response_model=DelayMap)
def delay_map(
    hour: int | None = Query(None, ge=0, le=23),
    colour_by: ColourBy = "overall",
    factors: str = "weather,time_of_day,events",
):
    enabled = [f for f in factors.split(",") if f]
    unknown = set(enabled) - VALID_FACTORS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown factors: {sorted(unknown)}")
    return mock_data.get_delay_map(_hour(hour), colour_by, enabled)


@router.post("/route", response_model=RouteResponse)
def route(req: RouteRequest):
    _require_stop(req.origin_id)
    _require_stop(req.destination_id)
    if req.origin_id == req.destination_id:
        raise HTTPException(status_code=400, detail="Origin and destination must differ")
    return mock_data.get_route_response(req.origin_id, req.destination_id, req.mode, req.time)


@router.get("/typical-delay", response_model=TypicalDelay)
def typical_delay(from_id: str, to_id: str, hour: int | None = Query(None, ge=0, le=23)):
    _require_stop(from_id)
    _require_stop(to_id)
    return mock_data.get_typical_delay(from_id, to_id, _hour(hour))