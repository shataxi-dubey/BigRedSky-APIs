"""Pydantic request and response schemas for the Resume Summary API."""

from typing import List

from pydantic import BaseModel, Field


class SummaryRequest(BaseModel):
    """Request body for POST /api/v1/resume/summary."""

    candidate_id: str = Field(..., description="Unique identifier for the candidate.")
    jd_id: str = Field(..., description="Identifier of the finalised job description.")
    jd_html: str = Field(..., description="Full HTML content of the job description.")
    resume_s3_path: str = Field(..., description="S3 object key of the candidate's resume file.")
    force_refresh: bool = Field(False, description="Regenerate even if a summary already exists.")


class SummaryData(BaseModel):
    """Structured summary produced by the LLM."""

    professional_profile: str
    strengths: List[str]
    skill_gaps: List[str]
    experience_relevance: str
    red_flags: List[str]
    notable_items: List[str]


class SummaryResponse(BaseModel):
    """Response body for POST /api/v1/resume/summary."""

    candidate_id: str
    jd_id: str
    summary: SummaryData