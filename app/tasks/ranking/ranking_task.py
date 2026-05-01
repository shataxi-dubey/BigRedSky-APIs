"""Celery task for async AI candidate scoring."""

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import SecretStr
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select

from app.constants.constants import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PROCESSING,
)
from app.core.config import settings
from app.core.database import RankingCriteria, RankingScoringJob, async_session_factory
from app.tasks.celery_main import celery_app
from app.workflows.graphs.ranking.prompts import SCORER_PROMPT


# ─── Lazy singletons ──────────────────────────────────────────────────────────

_qdrant_client: Optional[QdrantClient] = None
_ranking_llm: Optional[ChatOpenAI] = None


def _get_qdrant() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY or None,
        )
    return _qdrant_client


def _get_llm() -> ChatOpenAI:
    global _ranking_llm
    if _ranking_llm is None:
        _ranking_llm = ChatOpenAI(
            model=settings.RANKING_LLM_MODEL,
            api_key=SecretStr(settings.OPENAI_API_KEY),
        )
    return _ranking_llm


# ─── Resume reconstruction ────────────────────────────────────────────────────

def _fetch_candidate_resume(candidate_id: str) -> str:
    qdrant = _get_qdrant()
    points, _ = qdrant.scroll(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        scroll_filter=Filter(
            must=[FieldCondition(key="candidate_id", match=MatchValue(value=candidate_id))]
        ),
        limit=200,
        with_payload=True,
        with_vectors=False,
    )
    if not points:
        return ""
    parts = []
    for point in sorted(points, key=lambda p: p.payload.get("section_name", "")):
        section = point.payload.get("section_name", "")
        text = point.payload.get("text", "")
        if text:
            parts.append(f"## {section}\n{text}")
    return "\n\n".join(parts)


# ─── Scorer LLM call + output parsing ────────────────────────────────────────

def _score_candidate(criteria_dict: dict, resume_text: str) -> Dict[str, Any]:
    """Call the scorer LLM and parse the JSON section from the response."""
    human_content = (
        f"### Criteria Rubric\n{json.dumps(criteria_dict, indent=2)}\n\n"
        f"### Resume\n{resume_text}"
    )
    llm = _get_llm()
    response = llm.invoke(
        [
            SystemMessage(content=SCORER_PROMPT),
            HumanMessage(content=human_content),
        ]
    )
    raw = str(response.content)
    return _parse_scorer_json(raw)


def _parse_scorer_json(raw: str) -> Dict[str, Any]:
    match = re.search(r"===JSON_START===(.*?)===JSON_END===", raw, re.DOTALL)
    if not match:
        raise ValueError("Scorer response missing ===JSON_START=== / ===JSON_END=== delimiters")
    json_text = match.group(1).strip()
    return json.loads(json_text)


# ─── Async core (DB operations) ───────────────────────────────────────────────

async def _run_scoring(job_id: str) -> None:
    job_uuid = uuid.UUID(job_id)

    async with async_session_factory() as db:
        job: Optional[RankingScoringJob] = await db.get(RankingScoringJob, job_uuid)
        if job is None:
            logger.error(f"score_candidates: job not found job_id={job_id}")
            return
        job.status = JOB_STATUS_PROCESSING
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()

        candidate_ids: List[str] = job.candidate_ids
        jd_id: str = job.jd_id

    # Load criteria
    async with async_session_factory() as db:
        result = await db.execute(
            select(RankingCriteria).where(RankingCriteria.jd_id == jd_id)
        )
        criteria_record = result.scalar_one_or_none()

    if criteria_record is None:
        async with async_session_factory() as db:
            job = await db.get(RankingScoringJob, job_uuid)
            if job:
                job.status = JOB_STATUS_FAILED
                job.error_message = f"No criteria found for jd_id={jd_id}"
                job.updated_at = datetime.now(timezone.utc)
                await db.commit()
        return

    criteria_dict = json.loads(criteria_record.criteria_json)

    # Score each candidate sequentially
    results = []
    for candidate_id in candidate_ids:
        try:
            resume_text = _fetch_candidate_resume(candidate_id)
            if not resume_text:
                logger.warning(f"No Qdrant chunks for candidate_id={candidate_id}")
                results.append({
                    "candidate_id": candidate_id,
                    "scorer_output": None,
                    "error": "No resume chunks found in vector store",
                })
                continue
            scorer_output = _score_candidate(criteria_dict, resume_text)
            results.append({"candidate_id": candidate_id, "scorer_output": scorer_output})
            logger.info(f"Scored candidate_id={candidate_id}")
        except Exception as exc:
            logger.error(f"Failed to score candidate_id={candidate_id}: {exc}")
            results.append({
                "candidate_id": candidate_id,
                "scorer_output": None,
                "error": str(exc),
            })

    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        job = await db.get(RankingScoringJob, job_uuid)
        if job:
            job.status = JOB_STATUS_COMPLETED
            job.results = results
            job.completed_at = now
            job.updated_at = now
            await db.commit()

    logger.info(
        f"score_candidates: completed job_id={job_id} "
        f"scored={len([r for r in results if r.get('scorer_output')])}/"
        f"{len(candidate_ids)}"
    )


# ─── Celery task ──────────────────────────────────────────────────────────────

@celery_app.task(name="score_candidates", bind=True, max_retries=3)
def score_candidates(self, job_id: str) -> None:
    """Score all candidates for a job using the stored criteria rubric."""
    try:
        asyncio.run(_run_scoring(job_id))
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60)
        raise
