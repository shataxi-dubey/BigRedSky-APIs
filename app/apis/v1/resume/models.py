"""Pydantic request and response schemas for the Resume Parser."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ─── LLM structured-output schema (used by extract_fields graph node) ────

class WorkExperience(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None


class Education(BaseModel):
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    graduation_year: Optional[str] = None


class ParsedResume(BaseModel):
    """Structured resume data extracted by the LLM."""

    summary: Optional[str] = None
    work_experience: List[WorkExperience] = []
    education: List[Education] = []
    skills: List[str] = []
    certifications: List[str] = []
    languages: List[str] = []


# ─── API response schemas ─────────────────────────────────────────────────

class ParseJobResponse(BaseModel):
    job_id: str
    chunk_job_id: str
    status: str
    message: str


class ParseJobStatusResponse(BaseModel):
    job_id: str
    candidate_id: str
    status: str
    pii_entities: Optional[List[Dict[str, str]]] = None
    parsed_result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class ChunkStatusResponse(BaseModel):
    chunk_job_id: str
    candidate_id: str
    status: str
    chunk_count: Optional[int] = None
    error_message: Optional[str] = None


class RetryResponse(BaseModel):
    job_id: str
    status: str
    message: str
