"""JD Creator API endpoints."""

from fastapi.routing import APIRouter
from fastapi_utils.cbv import cbv

from app.constants.messages import JD_REPHRASED
from app.core.responses import AppJSONResponse, AppStreamingResponse

from .models import GenerateRequest, RephraseRequest, RephraseResponse
from .service import JDService

router = APIRouter()


@cbv(router)
class JDRoute:
    """JD Creator endpoints: generate (with built-in refinement) and rephrase."""

    def __init__(self):
        self.service = JDService()

    @router.post("/jd/generate", response_class=AppStreamingResponse)
    async def generate(self, body: GenerateRequest):
        """Generate or refine a job description.

        First call: provide input_type + content field. Returns session_id + jd_id in metadata.
        Subsequent calls: provide session_id + raw_text (refinement instruction).
        Streams the JD token by token via SSE. Final event is 'metadata' with session info.
        """
        stream = await self.service.generate_jd(body)
        return AppStreamingResponse(data_stream=stream)

    @router.post("/jd/rephrase")
    async def rephrase(self, body: RephraseRequest):
        """Rephrase a user-selected passage within a JD."""
        original, rephrased = await self.service.rephrase_jd(body)
        data = RephraseResponse(original_text=original, rephrased_text=rephrased).model_dump()
        return AppJSONResponse(data=data, message=JD_REPHRASED)
