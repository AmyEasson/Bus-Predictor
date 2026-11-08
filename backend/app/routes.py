
from fastapi import APIRouter, HTTPException, Query
import pandas as pd
from typing import Optional
from .database import get_db_connection
import numpy as np
from datetime import date

from .services.stops import search_bus_stops
from .services.journey import (
    find_direct_journeys,
    find_transfer_journeys
)

router = APIRouter(prefix="/api", tags=["buses"])


@router.get("/stops/search")
def search_stops(
    q: str = Query(..., min_length=2),
    limit: int = Query(10, ge=1, le=50)
):
    try:
        search_term = q.strip()

        if len(search_term) < 2:
            raise HTTPException(
                status_code=400,
                detail="Search term must contain at least 2 characters"
            )

        # Use the dedicated stops service (automatically filters Metrolink and sorts)
        return search_bus_stops(search_term, limit=limit)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
def api_root():
    """Welcome message for the API."""
    return {"message": "Another Bus API is running live!"}


@router.get("/routes")
def get_routes():
    """Get active bus routes and their current vehicle counts."""
    try:
        con = get_db_connection()
        query = """
            SELECT published_line_name, COUNT(DISTINCT operator_ref || vehicle_ref) AS active_buses
            FROM positions
            WHERE published_line_name IS NOT NULL AND published_line_name != ''
            GROUP BY published_line_name
            ORDER BY active_buses DESC;
        """
        df = pd.read_sql(query, con)
        con.close()
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/buses/{line_name}")
def get_buses_for_route(
    line_name: str,
    limit: Optional[int] = Query(100, le=500)
):
    """Get the latest recorded GPS points for a specific route."""
    try:
        con = get_db_connection()
        query = """
            SELECT operator_ref, vehicle_ref, published_line_name, destination_name,
                   latitude, longitude, bearing, recorded_at
            FROM positions
            WHERE published_line_name = ?
            ORDER BY recorded_at DESC
            LIMIT ?;
        """
        df = pd.read_sql(query, con, params=(line_name, limit))
        con.close()
        df = df.replace({np.nan: None, np.inf: None, -np.inf: None})
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/buses/all/live")
def get_all_live_buses(limit: Optional[int] = Query(150, le=500)):
    """Get latest GPS points for all routes to populate the default map view."""
    try:
        con = get_db_connection()
        query = """
           SELECT p.operator_ref, p.vehicle_ref, p.published_line_name, p.destination_name,
                p.latitude, p.longitude, p.bearing, p.recorded_at
            FROM positions p
            JOIN (SELECT operator_ref, vehicle_ref, MAX(recorded_at) AS latest
                    FROM positions
                    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                    GROUP BY operator_ref, vehicle_ref) l
            ON p.operator_ref = l.operator_ref
            AND p.vehicle_ref = l.vehicle_ref
            AND p.recorded_at = l.latest
            LIMIT ?;
        """
        df = pd.read_sql(query, con, params=(limit,))
        con.close()
        df = df.replace({np.nan: None, np.inf: None, -np.inf: None})
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journeys")
def get_journeys(
    origin_stop_id: str = Query(..., min_length=1),
    destination_stop_id: str = Query(..., min_length=1),
    travel_date: date = Query(...),
    limit: int = Query(10, ge=1, le=50),
    include_stops: bool = Query(False),
    departure_after: Optional[str] = Query(
        None,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d"
    ),
    arrive_by: Optional[str] = Query(
        None,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d"
    )
):
    """Find direct and one-transfer bus journeys operating on a selected date."""

    try:
        # Find journeys that use a single bus.
        direct_journeys = find_direct_journeys(
            origin_stop_id=origin_stop_id,
            destination_stop_id=destination_stop_id,
            travel_date=travel_date,
            limit=limit,
            departure_after=departure_after,
            arrive_by=arrive_by
        )

        # Find journeys that require changing buses once.
        transfer_journeys = find_transfer_journeys(
            origin_stop_id=origin_stop_id,
            destination_stop_id=destination_stop_id,
            travel_date=travel_date,
            limit=limit,
            departure_after=departure_after,
            arrive_by=arrive_by
        )

        # Identify direct journeys so the frontend can distinguish them
        # from journeys involving a transfer.
        for journey in direct_journeys:
            journey["journey_type"] = "direct"

        # Combine both types of journey.
        journeys = direct_journeys + transfer_journeys

        # Sort all results by departure time.
        journeys.sort(
            key=lambda journey: journey["departure_time"]
        )

        # Apply the requested limit to the combined results.
        journeys = journeys[:limit]

        # Remove stop details if they were not requested.
        if not include_stops:
            for journey in journeys:
                journey.pop("stops", None)

                # Transfer journeys also contain stop details
                # inside each individual leg.
                if journey.get("journey_type") == "transfer":
                    for leg in journey.get("legs", []):
                        leg.pop("stops", None)

        return {
            "origin_stop_id": origin_stop_id,
            "destination_stop_id": destination_stop_id,
            "travel_date": travel_date.isoformat(),
            "journey_count": len(journeys),
            "journeys": journeys
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
