"""Initialize API Routers"""

from fastapi import APIRouter

from .contact.controller import router as contact_router
from .jd.controller import router as jd_router
from .resume_summary.controller import router as resume_router

# Define and configure versioned API routers
v1_routers = APIRouter()
v1_routers.include_router(jd_router, tags=["JD Creator"])
v1_routers.include_router(resume_router, tags=["Resume Summary"])
v1_routers.include_router(contact_router, tags=["Contact Draft"])

__all__ = ["v1_routers"]
