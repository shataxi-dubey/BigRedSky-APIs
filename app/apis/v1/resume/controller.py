"""Resume Summary API endpoints."""

from fastapi import Request
from fastapi.routing import APIRouter
from fastapi_utils.cbv import cbv

from app.constants.messages import RESUME_SUMMARY_DELETED, RESUME_SUMMARY_GENERATED
from app.core.responses import AppJSONResponse

from .models import DeleteSummaryResponse, SummaryRequest, SummaryResponse
from .service import SummaryService

router = APIRouter()


@cbv(router)
class ResumeRoute:
    """Resume Summary endpoints."""

    def __init__(self):
        self.service = SummaryService()

    @router.post("/resume/summary")
    async def generate_summary(self, request: Request, body: SummaryRequest):
        """Generate a JD-aware summary for a candidate's resume."""
        result: SummaryResponse = await self.service.generate(body)
        return AppJSONResponse(data=result.model_dump(), message=RESUME_SUMMARY_GENERATED)

    @router.delete("/resume/summary/{candidate_id}/{jd_id}")
    async def delete_summary(self, request: Request, candidate_id: str, jd_id: str):
        """Delete the persisted summary for a candidate + JD pair."""
        await self.service.invalidate(candidate_id, jd_id)
        result = DeleteSummaryResponse(candidate_id=candidate_id, jd_id=jd_id)
        return AppJSONResponse(data=result.model_dump(), message=RESUME_SUMMARY_DELETED)
