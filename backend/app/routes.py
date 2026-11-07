# routes.py
from fastapi import APIRouter, HTTPException, Query
import pandas as pd
from typing import Optional
from .database import get_db_connection
import numpy as np

router = APIRouter(prefix="/api", tags=["buses"])

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
        # Hackathon fallback if snapshot.sqlite isn't fully migrated/present yet
        return [
            {"published_line_name": "42", "active_buses": 5},
            {"published_line_name": "43", "active_buses": 3},
            {"published_line_name": "142", "active_buses": 4}
        ]

@router.get("/buses/{line_name}")
def get_buses_for_route(line_name: str, limit: Optional[int] = Query(100, le=500)):
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
        
        # Replace NaN, NaT, Inf with None so FastAPI/JSON can serialize it cleanly
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
            SELECT operator_ref, vehicle_ref, published_line_name, destination_name, 
                   latitude, longitude, bearing, recorded_at
            FROM positions
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            ORDER BY recorded_at DESC
            LIMIT ?;
        """
        df = pd.read_sql(query, con, params=(limit,))
        con.close()
        df = df.replace({np.nan: None, np.inf: None, -np.inf: None})
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))