"""Contact Draft API endpoints."""

from fastapi import Request
from fastapi.routing import APIRouter
from fastapi_utils.cbv import cbv

from app.constants.messages import CONTACT_DRAFTED
from app.core.responses import AppJSONResponse

from .models import DraftRequest, DraftResponse
from .service import ContactService

router = APIRouter()


@cbv(router)
class ContactRoute:
    """Contact Draft endpoint: generate a personalised outreach email."""

    def __init__(self):
        self.service = ContactService()

    @router.post("/contact/draft")
    async def draft(self, request: Request, body: DraftRequest):
        """Draft a personalised outreach email from a template or raw text."""
        result: DraftResponse = await self.service.draft(body)
        return AppJSONResponse(data=result.model_dump(), message=CONTACT_DRAFTED)
