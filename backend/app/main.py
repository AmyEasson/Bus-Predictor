
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
 
from .routes import router
from .delay_routes import router as delay_router
from .mock_routes import router as mock_router
 
app = FastAPI(title="Bus delay API", version="0.3.0")
 
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
app.include_router(mock_router, prefix="/api")