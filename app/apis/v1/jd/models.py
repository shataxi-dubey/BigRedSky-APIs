"""Pydantic request and response schemas for the JD Creator API."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class JobDetails(BaseModel):
    """Structured job details used when input_type is 'details'."""

    job_title: str
    department: str
    location: str
    employment_type: str
    responsibilities: List[str]
    required_skills: List[str]
    preferred_skills: List[str] = Field(default_factory=list)
    compensation_range: str = ""


class GenerateRequest(BaseModel):
    """Request body for POST /api/v1/jd/generate."""

    input_type: Literal["raw_text", "template", "details"]
    raw_text: Optional[str] = None
    template: Optional[str] = None
    details: Optional[JobDetails] = None

    @model_validator(mode="after")
    def validate_input_fields(self) -> "GenerateRequest":
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


class ConversationMessage(BaseModel):
    """A single turn in the JD refinement conversation history."""

    role: Literal["user", "assistant"]
    content: str


class RefineRequest(BaseModel):
    """Request body for POST /api/v1/jd/refine."""

    instruction: str = Field(description="Natural-language instruction to apply to the JD.")
    messages: List[ConversationMessage] = Field(
        description="Conversation history: alternating assistant (JD) and user (instruction) turns."
    )
    refinements_remaining: int = Field(
        description="Number of refinements the caller still allows. Must be > 0.",
        ge=0,
    )
