"""Business logic for the JD Creator feature."""

import json
from typing import AsyncGenerator, Callable, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import SecretStr

from app import settings
from app.constants.messages import REFINEMENT_LIMIT_REACHED
from app.core.exceptions.base import CustomException
from app.workflows.graphs.jd.prompts import GENERATE_PROMPT, REFINE_PROMPT, REPHRASE_PROMPT

from .models import GenerateRequest, RefineRequest, RephraseRequest


class JDService:
    """Handles JD generation, rephrasing, and refinement via direct LLM calls."""

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.JD_LLM_MODEL,
            api_key=SecretStr(settings.OPENAI_API_KEY),
        )

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------

    async def generate_jd(
        self, request: GenerateRequest
    ) -> Callable[[], AsyncGenerator[str, None]]:
        """Stream a generated JD as SSE events."""
        messages = [
            SystemMessage(content=GENERATE_PROMPT),
            HumanMessage(content=self._build_generate_content(request)),
        ]

        llm = self.llm

        async def stream() -> AsyncGenerator[str, None]:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    yield f"event: content\ndata: {json.dumps(chunk.content)}\n\n"
            yield "event: complete\ndata: [DONE]\n\n"

        return stream

    @staticmethod
    def _build_generate_content(request: GenerateRequest) -> str:
        if request.input_type == "raw_text":
            return f"Generate a job description from the following raw text:\n\n{request.raw_text}"
        if request.input_type == "template":
            return f"Generate a job description by filling in the following template:\n\n{request.template}"
        d = request.details
        responsibilities = "\n".join(f"- {r}" for r in d.responsibilities)
        required_skills = "\n".join(f"- {s}" for s in d.required_skills)
        preferred_skills = "\n".join(f"- {s}" for s in d.preferred_skills)
        return (
            f"Generate a job description for the following role:\n\n"
            f"Job Title: {d.job_title}\n"
            f"Department: {d.department}\n"
            f"Location: {d.location}\n"
            f"Employment Type: {d.employment_type}\n"
            f"Responsibilities:\n{responsibilities}\n"
            f"Required Skills:\n{required_skills}\n"
            f"Preferred Skills:\n{preferred_skills}\n"
            f"Compensation Range: {d.compensation_range}"
        )

    # ------------------------------------------------------------------
    # Rephrase
    # ------------------------------------------------------------------

    async def rephrase_jd(self, request: RephraseRequest) -> Tuple[str, str]:
        """Return (original_text, rephrased_text)."""
        tone = request.tone or "professional"
        prompt = REPHRASE_PROMPT.format(tone=tone, selected_text=request.selected_text)
        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        logger.info("Rephrasing complete.")
        return request.selected_text, response.content

    # ------------------------------------------------------------------
    # Refine
    # ------------------------------------------------------------------

    async def refine_jd(
        self, request: RefineRequest
    ) -> Callable[[], AsyncGenerator[str, None]]:
        """Validate the refinement cap then stream the refined JD."""
        if request.refinements_remaining <= 0:
            raise CustomException(
                message=REFINEMENT_LIMIT_REACHED,
                status_code=429,
                error_log=REFINEMENT_LIMIT_REACHED,
            )

        messages = [SystemMessage(content=REFINE_PROMPT), *self._build_refine_messages(request)]
        refinements_left = request.refinements_remaining - 1
        llm = self.llm

        async def stream() -> AsyncGenerator[str, None]:
            async for chunk in llm.astream(messages):
                if chunk.content:
                    yield f"event: content\ndata: {json.dumps(chunk.content)}\n\n"
            yield f"event: metadata\ndata: {json.dumps({'refinements_remaining': refinements_left})}\n\n"
            yield "event: complete\ndata: [DONE]\n\n"

        return stream

    @staticmethod
    def _build_refine_messages(request: RefineRequest):
        lc_messages = []
        for msg in request.messages:
            if msg.role == "assistant":
                lc_messages.append(AIMessage(content=msg.content))
            else:
                lc_messages.append(HumanMessage(content=msg.content))
        lc_messages.append(HumanMessage(content=request.instruction))
        return lc_messages
