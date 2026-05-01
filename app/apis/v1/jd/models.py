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

    First call: provide input_type + the matching content field. session_id must be absent.
    Subsequent calls: provide session_id + raw_text as the refinement instruction.
    """

    input_type: Optional[Literal["raw_text", "template", "details"]] = None
    raw_text: Optional[str] = None
    template: Optional[str] = None
    details: Optional[JobDetails] = None
    session_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_input_fields(self) -> "GenerateRequest":
        if self.session_id:
            if not self.raw_text:
                raise ValueError("raw_text (refinement instruction) is required when session_id is provided.")
        else:
            if not self.input_type:
                raise ValueError("input_type is required for the initial generation.")
            if self.input_type == "raw_text" and not self.raw_text:
                raise ValueError("raw_text is required when input_type is 'raw_text'.")
            if self.input_type == "template" and not self.template:
                raise ValueError("template is required when input_type is 'template'.")
            if self.input_type == "details" and not self.details:
                raise ValueError("details is required when input_type is 'details'.")
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
