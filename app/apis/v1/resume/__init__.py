"""Resume API router."""

from fastapi import APIRouter

from .controller import router as _resume_router

router = APIRouter()
router.include_router(_resume_router)

__all__ = ["router"]
