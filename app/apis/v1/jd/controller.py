"""JD Creator API endpoints."""

from fastapi import Request
from fastapi.routing import APIRouter
from fastapi_utils.cbv import cbv

from app.constants.messages import JD_REPHRASED
from app.core.responses import AppJSONResponse, AppStreamingResponse

from .models import GenerateRequest, RefineRequest, RephraseRequest, RephraseResponse
from .service import JDService

router = APIRouter()


@cbv(router)
class JDRoute:
    """JD Creator endpoints: generate, rephrase, and refine."""

    def __init__(self):
        self.service = JDService()

    @router.post("/jd/generate", response_class=AppStreamingResponse)
    async def generate(self, request: Request, body: GenerateRequest):
        """Generate a job description from raw text, a template, or structured details.

        Streams the Markdown JD token by token via SSE.
        """
        stream = await self.service.generate_jd(body)
        return AppStreamingResponse(data_stream=stream)

    @router.post("/jd/rephrase")
    async def rephrase(self, request: Request, body: RephraseRequest):
        """Rephrase a user-selected passage within a JD."""
        original, rephrased = await self.service.rephrase_jd(body)
        data = RephraseResponse(original_text=original, rephrased_text=rephrased).model_dump()
        return AppJSONResponse(data=data, message=JD_REPHRASED)

    @router.post("/jd/refine", response_class=AppStreamingResponse)
    async def refine(self, request: Request, body: RefineRequest):
        """Apply a natural-language instruction to refine the full JD.

        Streams the updated Markdown JD via SSE. A final 'metadata' event
        carries the updated refinements_remaining count.
        """
        stream = await self.service.refine_jd(body)
        return AppStreamingResponse(data_stream=stream)
