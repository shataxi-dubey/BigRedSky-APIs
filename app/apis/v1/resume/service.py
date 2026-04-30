"""Business logic for the Resume Summary feature."""

import json
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app import settings
from app.core.db import AsyncSessionLocal, ResumeSummary
from app.core.exceptions.base import CustomException
from app.constants.messages import (
    RESUME_SUMMARY_NOT_FOUND,
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

    async def generate(self, request: SummaryRequest) -> SummaryResponse:
        """Full pipeline: fetch → parse → scrub → summarise → persist."""
        if not request.force_refresh:
            existing = await self._load_from_db(request.candidate_id, request.jd_id)
            if existing:
                logger.info(
                    f"Returning existing summary for candidate={request.candidate_id} jd={request.jd_id}"
                )
                return existing

        file_bytes, filename = await fetch_resume_from_s3(request.resume_s3_path)
        resume_text = parse_resume_file(file_bytes, filename)
        scrubbed_resume = scrub_pii(resume_text)
        jd_text = html_to_text(request.jd_html)

        summary_data = await self._call_llm(scrubbed_resume, jd_text)
        generated_at = datetime.now(timezone.utc)

        await self._upsert_db(request.candidate_id, request.jd_id, summary_data, generated_at)

        return SummaryResponse(
            candidate_id=request.candidate_id,
            jd_id=request.jd_id,
            generated_at=generated_at,
            summary=summary_data,
        )

    async def invalidate(self, candidate_id: str, jd_id: str) -> None:
        """Delete the persisted summary for a candidate + JD pair."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ResumeSummary).where(
                    ResumeSummary.candidate_id == candidate_id,
                    ResumeSummary.jd_id == jd_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                raise CustomException(
                    message=RESUME_SUMMARY_NOT_FOUND, status_code=404
                )
            await session.delete(row)
            await session.commit()
            logger.info(f"Deleted summary for candidate={candidate_id} jd={jd_id}")

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

    @staticmethod
    async def _load_from_db(candidate_id: str, jd_id: str):
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ResumeSummary).where(
                    ResumeSummary.candidate_id == candidate_id,
                    ResumeSummary.jd_id == jd_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return SummaryResponse(
                candidate_id=row.candidate_id,
                jd_id=row.jd_id,
                generated_at=row.generated_at,
                summary=SummaryData(
                    professional_profile=row.professional_profile,
                    strengths=row.strengths,
                    skill_gaps=row.skill_gaps,
                    experience_relevance=row.experience_relevance,
                    red_flags=row.red_flags,
                    notable_items=row.notable_items,
                ),
            )

    @staticmethod
    async def _upsert_db(
        candidate_id: str, jd_id: str, data: SummaryData, generated_at: datetime
    ) -> None:
        now = datetime.now(timezone.utc)
        stmt = (
            insert(ResumeSummary)
            .values(
                candidate_id=candidate_id,
                jd_id=jd_id,
                professional_profile=data.professional_profile,
                strengths=data.strengths,
                skill_gaps=data.skill_gaps,
                experience_relevance=data.experience_relevance,
                red_flags=data.red_flags,
                notable_items=data.notable_items,
                generated_at=generated_at,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_candidate_jd",
                set_=dict(
                    professional_profile=data.professional_profile,
                    strengths=data.strengths,
                    skill_gaps=data.skill_gaps,
                    experience_relevance=data.experience_relevance,
                    red_flags=data.red_flags,
                    notable_items=data.notable_items,
                    generated_at=generated_at,
                    updated_at=now,
                ),
            )
        )
        async with AsyncSessionLocal() as session:
            await session.execute(stmt)
            await session.commit()
        logger.info(f"Upserted summary for candidate={candidate_id} jd={jd_id}")
