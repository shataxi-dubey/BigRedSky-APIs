"""FastAPI controller for the AI Ranking feature."""

from fastapi import File, Form, UploadFile
from fastapi.routing import APIRouter
from fastapi_utils.cbv import cbv

from app.constants.messages import (
    RANKING_CRITERIA_GENERATED,
    RANKING_SCORE_JOB_QUEUED,
)
from app.core.responses.json_response import AppJSONResponse

from .models import ScoreRequest
from .service import RankingService

router = APIRouter()


@cbv(router)
class RankingController:

    def __init__(self):
        self.service = RankingService()

    @router.post("/ranking/criteria", status_code=201)
    async def generate_criteria(
        self,
        jd_id: str = Form(..., description="Finalised JD identifier."),
        jd_file: UploadFile = File(..., description="PDF, DOCX, or HTML file of the JD."),
    ) -> AppJSONResponse:
        file_bytes = await jd_file.read()
        result = await self.service.generate_criteria(
            jd_id=jd_id,
            file_bytes=file_bytes,
            filename=jd_file.filename or "",
            content_type=jd_file.content_type or "",
        )
        return AppJSONResponse(
            message=RANKING_CRITERIA_GENERATED,
            data=result.model_dump(mode="json"),
            status_code=201,
        )

    @router.get("/ranking/criteria/{jd_id}")
    async def get_criteria(self, jd_id: str) -> AppJSONResponse:
        result = await self.service.get_criteria(jd_id)
        return AppJSONResponse(
            message=RANKING_CRITERIA_GENERATED,
            data=result.model_dump(mode="json"),
        )

    @router.post("/ranking/score", status_code=202)
    async def score_candidates(self, body: ScoreRequest) -> AppJSONResponse:
        result = await self.service.create_score_job(body)
        return AppJSONResponse(
            message=RANKING_SCORE_JOB_QUEUED,
            data=result.model_dump(),
            status_code=202,
        )

    @router.get("/ranking/score/{job_id}")
    async def get_score_job(self, job_id: str) -> AppJSONResponse:
        result = await self.service.get_score_job(job_id)
        return AppJSONResponse(
            message=result.status,
            data=result.model_dump(mode="json"),
        )
