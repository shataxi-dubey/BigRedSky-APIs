"""Pydantic request and response schemas for the Contact Draft API."""

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class DraftRequest(BaseModel):
    """Request body for POST /api/v1/contact/draft."""

    template: Optional[str] = None
    raw_text: Optional[str] = None
    merge_fields: List[str] = Field(
        description="Merge field placeholders available for this draft, e.g. ['[*FirstName]', '[*JobTitle]'].",
    )

    @model_validator(mode="after")
    def validate_inputs(self) -> "DraftRequest":
        if not self.template and not self.raw_text:
            raise ValueError("At least one of 'template' or 'raw_text' must be provided.")
        return self


class DraftResponse(BaseModel):
    """Response body for POST /api/v1/contact/draft."""

    subject: str
    body: str
    merge_fields_used: List[str]
