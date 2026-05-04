"""Initialize API Routers"""

from fastapi import APIRouter

from .contact.controller import router as contact_router
from .jd.controller import router as jd_router
from .ranking.controller import router as ranking_router
from .resume.controller import router as resume_router
from .resume_summary.controller import router as resume_summary_router

v1_routers = APIRouter()
v1_routers.include_router(jd_router, tags=["JD Creator"])
v1_routers.include_router(resume_router, tags=["Resume Parser"])
v1_routers.include_router(resume_summary_router, tags=["Resume Summary"])
v1_routers.include_router(contact_router, tags=["Contact Draft"])
v1_routers.include_router(ranking_router, tags=["AI Ranking"])

__all__ = ["v1_routers"]
