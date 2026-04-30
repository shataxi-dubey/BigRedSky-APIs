"""Business logic for the Resume Summary feature."""

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import SecretStr

from app import settings
from app.core.exceptions.base import CustomException
from app.constants.messages import (
    RESUME_SUMMARY_PARSE_ERROR,
)
from app.workflows.graphs.summary import SUMMARY_PROMPT

from .helper import fetch_resume_from_s3, html_to_text, parse_resume_file, scrub_pii
from .models import SummaryData, SummaryRequest, SummaryResponse


class SummaryService:
    """Generates and persists JD-aware resume summaries."""

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.SUMMARY_LLM_MODEL,
            api_key=SecretStr(settings.OPENAI_API_KEY),
        )

    async def generate_from_file(
        self,
        candidate_id: str,
        jd_id: str,
        jd_html: str,
        file_bytes: bytes,
        filename: str,
        force_refresh: bool = False,
    ) -> SummaryResponse:
        """Same pipeline as generate() but accepts raw file bytes instead of an S3 path."""

        resume_text = parse_resume_file(file_bytes, filename)
        logger.info(f'Original resume {resume_text}')
        scrubbed_resume = scrub_pii(resume_text)
        logger.info(f'Scrubbed resume {scrubbed_resume}')
        jd_text = html_to_text(jd_html)

        summary_data = await self._call_llm(scrubbed_resume, jd_text)

        return SummaryResponse(
            candidate_id=candidate_id,
            jd_id=jd_id,
            summary=summary_data,
        )

    async def generate(self, request: SummaryRequest) -> SummaryResponse:
        """Full pipeline: fetch → parse → scrub → summarise → persist."""

        file_bytes, filename = await fetch_resume_from_s3(request.resume_s3_path)
        resume_text = parse_resume_file(file_bytes, filename)
        scrubbed_resume = scrub_pii(resume_text)
        jd_text = html_to_text(request.jd_html)

        summary_data = await self._call_llm(scrubbed_resume, jd_text)

        return SummaryResponse(
            candidate_id=request.candidate_id,
            jd_id=request.jd_id,
            summary=summary_data,
        )

    async def _call_llm(self, resume_text: str, jd_text: str) -> SummaryData:
        user_content = (
            f"### JOB DESCRIPTION\n{jd_text}\n\n### CANDIDATE RESUME\n{resume_text}"
        )
        messages = [
            SystemMessage(content=SUMMARY_PROMPT),
            HumanMessage(content=user_content),
        ]
        response = await self.llm.ainvoke(messages)
        logger.info("Resume summary LLM call complete.")
        return self._parse_response(str(response.content))

    @staticmethod
    def _parse_response(raw: str) -> SummaryData:
        try:
            data = json.loads(raw)
            return SummaryData(**data)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error(f"Failed to parse LLM summary response: {exc}\nRaw: {raw}")
            raise CustomException(
                message=RESUME_SUMMARY_PARSE_ERROR, status_code=500, error_log=str(exc)
            )