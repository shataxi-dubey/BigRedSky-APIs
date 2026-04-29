"""Resume Parser API endpoints."""

import json
from typing import List

from fastapi import File, Form, Request, UploadFile
from fastapi.routing import APIRouter
from fastapi_utils.cbv import cbv

from app.constants.messages import (
    RESUME_CHUNK_RETRY_QUEUED,
    RESUME_PARSE_QUEUED,
    RESUME_PARSE_RETRY_QUEUED,
)
from app.core.responses import AppJSONResponse

from .models import ChunkStatusResponse, ParseJobResponse, ParseJobStatusResponse, RetryResponse
from .service import ResumeService

router = APIRouter()


def _parse_form_fields(raw: str) -> List[str]:
    """Accept comma-separated string OR JSON array; return a plain list."""
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            result = json.loads(raw)
            return [str(f).strip() for f in result if str(f).strip()]
        except json.JSONDecodeError:
            pass
    return [f.strip() for f in raw.split(",") if f.strip()]


@cbv(router)
class ResumeRoute:
    """Resume Parser endpoints."""

    def __init__(self):
        self.service = ResumeService()

    @router.post("/resume/parse", status_code=202)
    async def parse(
        self,
        request: Request,
        resume: UploadFile = File(...),
        candidate_id: str = Form(...),
        form_fields: str = Form(
            default="",
            description=(
                "Comma-separated field names to extract, e.g. "
                "skills,work_experience,education,certifications,languages,summary  "
                "(JSON array also accepted)"
            ),
        ),
    ):
        """Accept a PDF or DOCX resume, queue parse + chunk jobs, return job IDs.

        - `resume`: PDF or DOCX file, max 10 MB
        - `candidate_id`: unique identifier for the candidate
        - `form_fields`: comma-separated or JSON-array field names (optional — extracts all if omitted)
        """
        fields = _parse_form_fields(form_fields)
        result = await self.service.parse_resume(resume, candidate_id, fields)
        data = ParseJobResponse(**result).model_dump()
        return AppJSONResponse(data=data, message=RESUME_PARSE_QUEUED, status_code=202)

    @router.get("/resume/parse/{job_id}/status")
    async def parse_status(self, request: Request, job_id: str):
        """Poll the status of a parse job by job_id."""
        result = await self.service.get_parse_status(job_id)
        data = ParseJobStatusResponse(**result).model_dump()
        return AppJSONResponse(data=data)

    @router.get("/resume/chunk/{candidate_id}/status")
    async def chunk_status(self, request: Request, candidate_id: str):
        """Poll the status of the background chunking job for a candidate."""
        result = await self.service.get_chunk_status(candidate_id)
        data = ChunkStatusResponse(**result).model_dump()
        return AppJSONResponse(data=data)

    @router.post("/resume/parse/{job_id}/retry", status_code=202)
    async def retry_parse(self, request: Request, job_id: str):
        """Re-queue a failed parse job. Returns 409 if the job is not in failed state."""
        result = await self.service.retry_parse_job(job_id)
        data = RetryResponse(**result).model_dump()
        return AppJSONResponse(data=data, message=RESUME_PARSE_RETRY_QUEUED, status_code=202)

    @router.post("/resume/chunk/{candidate_id}/retry", status_code=202)
    async def retry_chunk(self, request: Request, candidate_id: str):
        """Re-queue the latest failed chunk job for a candidate. Returns 409 if not in failed state."""
        result = await self.service.retry_chunk_job(candidate_id)
        data = RetryResponse(**result).model_dump()
        return AppJSONResponse(data=data, message=RESUME_CHUNK_RETRY_QUEUED, status_code=202)
