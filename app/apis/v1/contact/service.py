"""Business logic for the Contact Draft feature."""

import json
import uuid
from typing import AsyncGenerator, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import SecretStr
from sqlalchemy import select

from app import settings
from app.constants.messages import CONTACT_DRAFT_PARSE_ERROR
from app.core.database import ContactDraftSession, async_session_factory
from app.core.exceptions.base import CustomException
from app.workflows.graphs.contact.prompts import DRAFT_PROMPT, REFINE_PROMPT
from app.core.langfuse_handler import langfuse_handler

from .models import DraftRequest


class ContactService:
    """Drafts and refines outreach emails with server-side session persistence."""

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.CONTACT_LLM_MODEL,
            api_key=SecretStr(settings.OPENAI_API_KEY),
            callbacks=[langfuse_handler]
        )

    # ------------------------------------------------------------------
    # Draft / Refine (unified)
    # ------------------------------------------------------------------

    async def draft(
        self, request: DraftRequest
    ) -> Callable[[], AsyncGenerator[str, None]]:
        """Stream an email draft as SSE events.

        Looks up session_id (client-provided) in the DB.
        No existing session → initial draft.
        Existing session → refinement turn.
        """
        async with async_session_factory() as db:
            result = await db.execute(
                select(ContactDraftSession).where(ContactDraftSession.id == request.session_id)
            )
            session = result.scalar_one_or_none()

        if session is None:
            return await self._draft(request)
        return await self._refine(request, session)

    async def _draft(
        self, request: DraftRequest
    ) -> Callable[[], AsyncGenerator[str, None]]:
        """Handle initial email draft generation."""
        human_content = self._build_user_content(request)
        lc_messages = [
            SystemMessage(content=DRAFT_PROMPT),
            HumanMessage(content=human_content),
        ]

        session_id = request.session_id
        draft_id = uuid.uuid4()
        llm = self.llm

        async def stream() -> AsyncGenerator[str, None]:
            collected: list[str] = []
            async for chunk in llm.astream(lc_messages):
                if chunk.content:
                    collected.append(chunk.content)
                    yield f"event: content\ndata: {json.dumps(chunk.content)}\n\n"

            ai_text = "".join(collected)
            self._validate_draft_json(ai_text)

            messages = [
                {"role": "user", "content": human_content},
                {"role": "assistant", "content": ai_text},
            ]
            async with async_session_factory() as db:
                db.add(
                    ContactDraftSession(
                        id=session_id,
                        draft_id=draft_id,
                        draft_json=ai_text,
                        messages=messages,
                    )
                )
                await db.commit()

            logger.info(f"Contact draft session created: session_id={session_id} draft_id={draft_id}")
            metadata = {
                "session_id": str(session_id),
                "draft_id": str(draft_id),
            }
            yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
            yield "event: complete\ndata: [DONE]\n\n"

        return stream

    async def _refine(
        self, request: DraftRequest, session: ContactDraftSession
    ) -> Callable[[], AsyncGenerator[str, None]]:
        """Handle a refinement turn against an existing contact draft session."""
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
        draft_id = session.draft_id
        llm = self.llm

        async def stream() -> AsyncGenerator[str, None]:
            collected: list[str] = []
            async for chunk in llm.astream(lc_messages):
                if chunk.content:
                    collected.append(chunk.content)
                    yield f"event: content\ndata: {json.dumps(chunk.content)}\n\n"

            ai_text = "".join(collected)
            self._validate_draft_json(ai_text)

            updated_messages = session.messages + [
                {"role": "user", "content": request.raw_text},
                {"role": "assistant", "content": ai_text},
            ]

            async with async_session_factory() as db:
                result = await db.execute(
                    select(ContactDraftSession).where(ContactDraftSession.id == session_id)
                )
                record = result.scalar_one()
                record.messages = updated_messages
                record.draft_json = ai_text
                await db.commit()

            logger.info(f"Contact draft refined: session_id={session_id}")
            metadata = {
                "session_id": str(session_id),
                "draft_id": str(draft_id),
            }
            yield f"event: metadata\ndata: {json.dumps(metadata)}\n\n"
            yield "event: complete\ndata: [DONE]\n\n"

        return stream

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_content(request: DraftRequest) -> str:
        types = request.input_type or []
        parts: list[str] = []

        if "raw_text" in types and request.raw_text:
            parts.append(f"Recruiter instructions:\n{request.raw_text}")

        if "template" in types and request.template:
            parts.append(f"Email template:\n{request.template}")

        if request.merge_fields:
            fields_text = "\n".join(f"- {f}" for f in request.merge_fields)
            parts.append(f"Available merge field placeholders (use only these):\n{fields_text}")

        return "Draft an outreach email based on the following:\n\n" + "\n\n".join(parts)

    @staticmethod
    def _validate_draft_json(raw: str) -> None:
        """Raise a CustomException if the LLM response is not valid draft JSON."""
        try:
            data = json.loads(raw)
            if not all(k in data for k in ("subject", "body", "merge_fields_used")):
                raise KeyError("Missing required keys in draft JSON.")
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Failed to parse LLM draft response: {exc}\nRaw: {raw}")
            raise CustomException(
                message=CONTACT_DRAFT_PARSE_ERROR,
                status_code=500,
                error_log=str(exc),
            )
