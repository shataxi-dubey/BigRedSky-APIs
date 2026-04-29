"""Pydantic request and response schemas for the Contact Draft API."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class DraftRequest(BaseModel):
    """Request body for POST /api/v1/contact/draft."""

    input_type: Literal["template", "raw_text"]
    template: Optional[str] = None
    raw_text: Optional[str] = None
    custom_merge_fields: Optional[Dict[str, str]] = Field(
        default=None,
        description="Additional merge fields to incorporate, e.g. {'role': 'Engineer'}.",
    )

    @model_validator(mode="after")
    def validate_input_fields(self) -> "DraftRequest":
        if self.input_type == "template" and not self.template:
            raise ValueError("template is required when input_type is 'template'.")
        if self.input_type == "raw_text" and not self.raw_text:
            raise ValueError("raw_text is required when input_type is 'raw_text'.")
        return self


class DraftResponse(BaseModel):
    """Response body for POST /api/v1/contact/draft."""

    subject: str
    body: str
    merge_fields_used: List[str]
