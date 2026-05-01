"""Pydantic request and response schemas for the JD Creator API."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class JobDetails(BaseModel):
    """Structured job details used when input_type is 'details'."""

    job_title: Optional[str] = None
    job_role: Optional[str] = None
    department: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    is_fully_remote: Optional[bool] = None
    industry: Optional[str] = None
    job_function: Optional[str] = None
    employment_type: Optional[str] = None
    is_full_time: Optional[bool] = None
    responsibilities: Optional[List[str]] = None
    required_skills: Optional[List[str]] = None
    preferred_skills: Optional[List[str]] = Field(default=None)
    compensation_range: Optional[str] = None
    currency: Optional[str] = None


class GenerateRequest(BaseModel):
    """Request body for POST /api/v1/jd/generate.

    session_id is always supplied by the client. If no session exists for it in the
    DB the server treats the call as initial generation; otherwise as a refinement turn.
    At least one of raw_text, template, or details must be provided on every call.
    """

    session_id: str = Field(description="Client-generated session identifier.")
    input_type: Optional[List[Literal["raw_text", "template", "details"]]] = None
    raw_text: Optional[str] = None
    template: Optional[str] = None
    details: Optional[JobDetails] = None

    @model_validator(mode="after")
    def validate_input_fields(self) -> "GenerateRequest":
        if not any([self.raw_text, self.template, self.details]):
            raise ValueError("At least one of raw_text, template, or details must be provided.")
        return self


class RephraseRequest(BaseModel):
    """Request body for POST /api/v1/jd/rephrase."""

    jd_id: str = Field(description="Client-side identifier for the JD being edited.")
    selected_text: str = Field(description="The exact passage the user wants rephrased.")
    tone: Optional[str] = Field(
        default=None,
        description="Desired tone, e.g. 'formal', 'inclusive', 'concise'.",
    )


class RephraseResponse(BaseModel):
    """Response body for POST /api/v1/jd/rephrase."""

    original_text: str
    rephrased_text: str
