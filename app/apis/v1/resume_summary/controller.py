"""Resume Summary API endpoints."""

from fastapi import Form, Request, UploadFile
from fastapi.routing import APIRouter
from fastapi_utils.cbv import cbv

from app.constants.messages import RESUME_SUMMARY_GENERATED
from app.core.responses import AppJSONResponse

from .models import SummaryRequest, SummaryResponse
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

    @router.post("/test/resume/summary")
    async def test_generate_summary(
        self,
        request: Request,
        resume_file: UploadFile,
        candidate_id: str = Form(...),
        jd_id: str = Form(...),
        jd_html: str = Form(...),
        force_refresh: bool = Form(False),
    ):
        """Test endpoint: same pipeline as /resume/summary but accepts a direct file upload instead of an S3 path."""
        file_bytes = await resume_file.read()
        result: SummaryResponse = await self.service.generate_from_file(
            candidate_id=candidate_id,
            jd_id=jd_id,
            jd_html=jd_html,
            file_bytes=file_bytes,
            filename=resume_file.filename or "resume",
            force_refresh=force_refresh,
        )
        return AppJSONResponse(data=result.model_dump(), message=RESUME_SUMMARY_GENERATED)