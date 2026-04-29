"""Initialize API Routers"""

from fastapi import APIRouter

from .jd.controller import router as jd_router

# Define and configure versioned API routers
v1_routers = APIRouter()
v1_routers.include_router(jd_router, tags=["JD Creator"])

__all__ = ["v1_routers"]
