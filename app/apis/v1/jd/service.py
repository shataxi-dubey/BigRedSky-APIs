"""Business logic for the JD Creator feature."""

import json
import uuid
from typing import AsyncGenerator, Callable, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import SecretStr
from sqlalchemy import select

from app import settings
from app.constants.constants import MAX_REFINEMENTS
from app.constants.messages import JD_SESSION_NOT_FOUND, REFINEMENT_LIMIT_REACHED
from app.core.database import JDSession, async_session_factory
from app.core.exceptions.base import CustomException
from app.workflows.graphs.jd.prompts import GENERATE_PROMPT, REFINE_PROMPT, REPHRASE_PROMPT

from .models import GenerateRequest, RephraseRequest


class JDService:
    """Handles JD generation, rephrasing, and refinement via direct LLM calls."""

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.JD_LLM_MODEL,
            api_key=SecretStr(settings.OPENAI_API_KEY),
        )

    # ------------------------------------------------------------------
    # Generate / Refine (unified)
    # ------------------------------------------------------------------

    async def generate_jd(
        self, request: GenerateRequest
    ) -> Callable[[], AsyncGenerator[str, None]]:
        """Stream a generated or refined JD as SSE events.

        First call (no session_id): creates a new JDSession, generates the JD,
        persists human + AI messages to DB.

        Subsequent calls (session_id provided): loads session, appends the new
        refinement turn, streams the updated JD, persists updated messages.
        """
        if request.session_id:
            return await self._refine(request)
        return await self._generate(request)

    async def _generate(
        self, request: GenerateRequest
    ) -> Callable[[], AsyncGenerator[str, None]]:
        """Handle initial JD generation."""
        human_content = self._build_generate_content(request)
        lc_messages = [
            SystemMessage(content=GENERATE_PROMPT),
            HumanMessage(content=human_content),
        ]

        session_id = uuid.uuid4()
        jd_id = uuid.uuid4()
        llm = self.llm

        async def stream() -> AsyncGenerator[str, None]:
            collected: list[str] = []
            async for chunk in llm.astream(lc_messages):
                if chunk.content:
                    collected.append(chunk.content)
                    yield f"event: content\ndata: {json.dumps(chunk.content)}\n\n"

            ai_text = "".join(collected)
            messages = [
                {"role": "user", "content": human_content},
                {"role": "assistant", "content": ai_text},
            ]
            async with async_session_factory() as db:
                db.add(
                    JDSession(
                        id=session_id,
                        jd_id=jd_id,
                        jd_html=ai_text,
                        messages=messages,
                        refinements_remaining=MAX_REFINEMENTS,
                    )
                )
                await db.commit()

            logger.info(f"JD session created: session_id={session_id} jd_id={jd_id}")
            metadata = {
                "session_id": str(session_id),
                "jd_id": str(jd_id),
                "refinements_remaining": MAX_REFINEMENTS,
            }
            yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
            yield "event: complete\ndata: [DONE]\n\n"

        return stream

    async def _refine(
        self, request: GenerateRequest
    ) -> Callable[[], AsyncGenerator[str, None]]:
        """Handle a refinement turn against an existing JD session."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(JDSession).where(JDSession.id == uuid.UUID(request.session_id))
            )
            session = result.scalar_one_or_none()

        if session is None:
            raise CustomException(
                message=JD_SESSION_NOT_FOUND.format(session_id=request.session_id),
                status_code=404,
                error_log=f"JDSession not found: {request.session_id}",
            )

        if session.refinements_remaining <= 0:
            raise CustomException(
                message=REFINEMENT_LIMIT_REACHED,
                status_code=429,
                error_log=REFINEMENT_LIMIT_REACHED,
            )

        history_messages = [
            AIMessage(content=m["content"]) if m["role"] == "assistant" else HumanMessage(content=m["content"])
            for m in session.messages
        ]
        lc_messages = [
            SystemMessage(content=REFINE_PROMPT),
            *history_messages,
            HumanMessage(content=request.raw_text),
        ]

        session_id = session.id
        jd_id = session.jd_id
        refinements_left = session.refinements_remaining - 1
        llm = self.llm

        async def stream() -> AsyncGenerator[str, None]:
            collected: list[str] = []
            async for chunk in llm.astream(lc_messages):
                if chunk.content:
                    collected.append(chunk.content)
                    yield f"event: content\ndata: {json.dumps(chunk.content)}\n\n"

            ai_text = "".join(collected)
            updated_messages = session.messages + [
                {"role": "user", "content": request.raw_text},
                {"role": "assistant", "content": ai_text},
            ]

            async with async_session_factory() as db:
                result = await db.execute(
                    select(JDSession).where(JDSession.id == session_id)
                )
                record = result.scalar_one()
                record.messages = updated_messages
                record.jd_html = ai_text
                record.refinements_remaining = refinements_left
                await db.commit()

            logger.info(f"JD session refined: session_id={session_id} refinements_left={refinements_left}")
            metadata = {
                "session_id": str(session_id),
                "jd_id": str(jd_id),
                "refinements_remaining": refinements_left,
            }
            yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
            yield "event: complete\ndata: [DONE]\n\n"

        return stream

    @staticmethod
    def _build_generate_content(request: GenerateRequest) -> str:
        if request.input_type == "raw_text":
            return f"Generate a job description from the following raw text:\n\n{request.raw_text}"
        if request.input_type == "template":
            return f"Generate a job description by filling in the following template:\n\n{request.template}"
        d = request.details
        responsibilities = "\n".join(f"- {r}" for r in (d.responsibilities or []))
        required_skills = "\n".join(f"- {s}" for s in (d.required_skills or []))
        preferred_skills = "\n".join(f"- {s}" for s in (d.preferred_skills or []))
        return (
            f"Generate a job description for the following role:\n\n"
            f"Job Title: {d.job_title}\n"
            f"Job Role: {d.job_role}\n"
            f"Department: {d.department}\n"
            f"Country: {d.country}\n"
            f"State: {d.state}\n"
            f"City: {d.city}\n"
            f"Fully remote job: {d.is_fully_remote}\n"
            f"Industry: {d.industry}\n"
            f"Job function: {d.job_function}\n"
            f"Employment Type: {d.employment_type}\n"
            f"Full time job: {d.is_full_time}\n"
            f"Responsibilities:\n{responsibilities}\n"
            f"Required Skills:\n{required_skills}\n"
            f"Preferred Skills:\n{preferred_skills}\n"
            f"Compensation Range: {d.compensation_range}\n"
            f"Currency: {d.currency}"
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
