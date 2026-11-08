
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
 
from .routes import router
from .delay_routes import router as delay_router
from .stop_routes import router as stop_router
from .mock_routes import router as mock_router
 
def _warm_caches():
    """Load the timetable and stop summaries in the background, so the first search isn't ~4 s slow."""
    try:
        from .services.stop_info import stop_summaries
        stop_summaries()
    except Exception as e:  # never stop the server starting
        print(f"[startup] cache warm-up failed: {e}")


@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=_warm_caches, daemon=True).start()
    yield


app = FastAPI(title="Bus delay API", version="0.4.0", lifespan=lifespan)
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
 
 
@app.get("/health")
def health():
    return {"status": "ok"}
 
 
app.include_router(router)
app.include_router(delay_router)
app.include_router(stop_router)  # after routes.py, so /stops/search wins over /stops/{stop_id}
app.include_router(mock_router, prefix="/api")