"""Business logic for the Contact Draft feature."""

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import SecretStr

from app import settings
from app.constants.messages import CONTACT_DRAFT_PARSE_ERROR
from app.core.exceptions.base import CustomException
from app.workflows.graphs.contact.prompts import DRAFT_PROMPT

from .models import DraftRequest, DraftResponse


class ContactService:
    """Drafts outreach emails via a single synchronous LLM call."""

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.CONTACT_LLM_MODEL,
            api_key=SecretStr(settings.OPENAI_API_KEY),
        )

    async def draft(self, request: DraftRequest) -> DraftResponse:
        """Generate a single email draft and return the structured response."""
        user_content = self._build_user_content(request)
        messages = [
            SystemMessage(content=DRAFT_PROMPT),
            HumanMessage(content=user_content),
        ]
        response = await self.llm.ainvoke(messages)
        logger.info("Contact draft LLM call complete.")
        return self._parse_response(str(response.content))

    @staticmethod
    def _build_user_content(request: DraftRequest) -> str:
        parts = []

        if request.template and request.raw_text:
            parts.append(f"Use the following email template as the structural base:\n\n{request.template}")
            parts.append(f"Also incorporate the following recruiter instructions to personalise the draft:\n\n{request.raw_text}")
        elif request.template:
            parts.append(f"Draft an outreach email based on the following template:\n\n{request.template}")
        else:
            parts.append(f"Draft an outreach email based on the following recruiter instructions:\n\n{request.raw_text}")

        fields_text = "\n".join(f"- {f}" for f in request.merge_fields)
        parts.append(f"Available merge field placeholders (use only these, placed intelligently):\n{fields_text}")

        return "\n\n".join(parts)

    @staticmethod
    def _parse_response(raw: str) -> DraftResponse:
        try:
            data = json.loads(raw)
            return DraftResponse(
                subject=data["subject"],
                body=data["body"],
                merge_fields_used=data["merge_fields_used"],
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"Failed to parse LLM response: {exc}\nRaw: {raw}")
            raise CustomException(
                message=CONTACT_DRAFT_PARSE_ERROR,
                status_code=500,
                error_log=str(exc),
            )
