"""Contact Draft API endpoints."""

from fastapi.routing import APIRouter
from fastapi_utils.cbv import cbv

from app.core.responses import AppStreamingResponse

from .models import DraftRequest
from .service import ContactService

router = APIRouter()


@cbv(router)
class ContactRoute:
    """Contact Draft endpoint: generate and refine personalised outreach emails."""

    def __init__(self):
        self.service = ContactService()

    @router.post("/contact/draft", response_class=AppStreamingResponse)
    async def draft(self, body: DraftRequest):
        """Draft or refine a personalised outreach email.

        First call: provide session_id + input_type + content fields. Returns draft_id in metadata.
        Subsequent calls: provide session_id + raw_text (refinement instruction).
        Streams the draft JSON token by token via SSE. Final event is 'metadata' with session info.
        """
        stream = await self.service.draft(body)
        return AppStreamingResponse(data_stream=stream)
