"""Pydantic request and response schemas for the Contact Draft API."""

import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class DraftRequest(BaseModel):
    """Request body for POST /api/v1/contact/draft.

    session_id is always supplied by the client. If no session exists for it in the
    DB the server treats the call as the initial draft; otherwise as a refinement turn.
    At least one of raw_text or template must be provided on every call.
    """

    session_id: uuid.UUID = Field(description="Client-generated session identifier (UUID).")
    input_type: Optional[List[Literal["raw_text", "template"]]] = None
    raw_text: Optional[str] = None
    template: Optional[str] = None
    merge_fields: List[str] = Field(
        default_factory=list,
        description="Merge field placeholders available for this draft, e.g. ['[*FirstName]', '[*JobTitle]'].",
    )

    @model_validator(mode="after")
    def validate_inputs(self) -> "DraftRequest":
        if not any([self.raw_text, self.template]):
            raise ValueError("At least one of raw_text or template must be provided.")
        return self


class DraftResponse(BaseModel):
    """Response body for POST /api/v1/contact/draft."""

    subject: str
    body: str
    merge_fields_used: List[str]
