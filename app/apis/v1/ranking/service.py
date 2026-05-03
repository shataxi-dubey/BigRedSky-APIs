"""Business logic for the AI Ranking feature."""

import io
import json
import uuid
import time
from datetime import datetime, timezone
from typing import List, Optional

import fitz
from bs4 import BeautifulSoup
from docx import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import SecretStr
from sqlalchemy import delete, select

from app import settings
from app.constants.constants import JOB_STATUS_PENDING, RANKING_JD_ALLOWED_CONTENT_TYPES
from app.constants.messages import (
    RANKING_CRITERIA_NOT_FOUND,
    RANKING_CRITERIA_PARSE_ERROR,
    RANKING_JD_FILE_PARSE_ERROR,
    RANKING_JD_FILE_TYPE_ERROR,
    RANKING_SCORE_JOB_NOT_FOUND,
)
from app.core.database import RankingCriteria, RankingScoringJob, async_session_factory
from app.core.exceptions.base import CustomException
from app.workflows.graphs.ranking.prompts import (
    CRITERIA_GENERATOR_PROMPT,
    JD_ANALYSER_PROMPT,
)

from .models import (
    CandidateScoreResult,
    CleanAtomInput,
    CriteriaGeneratorOutput,
    CriteriaResponse,
    CriterionResponse,
    JDAnalysisOutput,
    RawAtom,
    RequirementCategory,
    RequirementDetail,
    RequirementItem,
    ScoreJobResponse,
    ScoreJobStatusResponse,
    ScoreRequest,
)


class RankingService:
    """Generates scoring criteria from a JD and scores candidates against them."""

    def __init__(self) -> None:
        self.llm = ChatOpenAI(
            model=settings.RANKING_LLM_MODEL,
            api_key=SecretStr(settings.OPENAI_API_KEY),
        )

    # ------------------------------------------------------------------
    # Criteria generation
    # ------------------------------------------------------------------

    async def generate_criteria(
        self,
        jd_id: str,
        file_bytes: bytes,
        filename: str,
        content_type: str,
    ) -> CriteriaResponse:
        """Run the two-prompt pipeline and persist the criteria (overwrite if exists)."""
        self._validate_jd_file_type(filename, content_type)

        jd_text = self._extract_jd_text(file_bytes, filename, content_type)
        start = time.time()
        analysis = await self._run_jd_analyser(jd_text)
        elapsed_time = time.time() - start
        logger.info(f"Total time elapsed in JD analysis {elapsed_time}")
        clean_atoms = self._dedup_atoms(analysis.raw_atoms)

        start = time.time()
        criteria_output = await self._run_criteria_generator(analysis.jd_title, clean_atoms)
        elapsed_time = time.time() - start
        logger.info(f"Total time elapsed in criteria generation {elapsed_time}")

        record = await self._persist_criteria(jd_id, criteria_output)
        return self._build_criteria_response(jd_id, record, criteria_output)

    async def get_criteria(self, jd_id: str) -> CriteriaResponse:
        """Retrieve stored criteria for a JD."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(RankingCriteria).where(RankingCriteria.jd_id == jd_id)
            )
            record = result.scalar_one_or_none()

        if record is None:
            raise CustomException(
                message=RANKING_CRITERIA_NOT_FOUND.format(jd_id=jd_id),
                status_code=404,
                error_log=f"jd_id={jd_id}",
            )

        criteria_output = CriteriaGeneratorOutput(**json.loads(record.criteria_json))
        return self._build_criteria_response(jd_id, record, criteria_output)

    # ------------------------------------------------------------------
    # Scoring jobs
    # ------------------------------------------------------------------

    async def create_score_job(self, request: ScoreRequest) -> ScoreJobResponse:
        """Validate criteria exist, create a job, queue the Celery task."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(RankingCriteria).where(RankingCriteria.jd_id == request.jd_id)
            )
            criteria_record = result.scalar_one_or_none()

        if criteria_record is None:
            raise CustomException(
                message=RANKING_CRITERIA_NOT_FOUND.format(jd_id=request.jd_id),
                status_code=404,
                error_log=f"jd_id={request.jd_id}",
            )

        job_id = uuid.uuid4()
        async with async_session_factory() as db:
            db.add(
                RankingScoringJob(
                    id=job_id,
                    jd_id=request.jd_id,
                    candidate_ids=request.candidate_ids,
                    status=JOB_STATUS_PENDING,
                )
            )
            await db.commit()

        from app.tasks.celery_main import celery_app
        celery_app.send_task("score_candidates", args=[str(job_id)])

        logger.info(
            f"Scoring job queued: job_id={job_id} jd_id={request.jd_id} "
            f"candidates={len(request.candidate_ids)}"
        )
        return ScoreJobResponse(
            job_id=str(job_id),
            status=JOB_STATUS_PENDING,
            candidate_count=len(request.candidate_ids),
        )

    async def get_score_job(self, job_id: str) -> ScoreJobStatusResponse:
        """Return current status and (if complete) scored results."""
        try:
            job_uuid = uuid.UUID(job_id)
        except ValueError:
            raise CustomException(
                message=RANKING_SCORE_JOB_NOT_FOUND.format(job_id=job_id),
                status_code=404,
                error_log=f"job_id={job_id} is not a valid UUID",
            )

        async with async_session_factory() as db:
            job = await db.get(RankingScoringJob, job_uuid)

        if job is None:
            raise CustomException(
                message=RANKING_SCORE_JOB_NOT_FOUND.format(job_id=job_id),
                status_code=404,
                error_log=f"job_id={job_id}",
            )

        results: Optional[List[CandidateScoreResult]] = None
        if job.results:
            results = [
                self._transform_scorer_output(entry["candidate_id"], entry["scorer_output"])
                for entry in job.results
                if entry.get("scorer_output") is not None
            ]

        return ScoreJobStatusResponse(
            job_id=str(job.id),
            jd_id=job.jd_id,
            status=job.status,
            completed_at=job.completed_at,
            candidate_count=len(job.candidate_ids),
            results=results,
        )

    # ------------------------------------------------------------------
    # Private: JD text extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_jd_file_type(filename: str, content_type: str) -> None:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        allowed_exts = {"pdf", "docx", "doc", "html", "htm"}
        if ext not in allowed_exts and content_type not in RANKING_JD_ALLOWED_CONTENT_TYPES:
            raise CustomException(
                message=RANKING_JD_FILE_TYPE_ERROR,
                status_code=400,
                error_log=f"ext={ext} content_type={content_type}",
            )

    @staticmethod
    def _extract_jd_text(file_bytes: bytes, filename: str, content_type: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        try:
            if ext == "pdf" or "pdf" in content_type:
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                return "\n".join(page.get_text() for page in doc)
            elif ext in ("docx", "doc") or "wordprocessingml" in content_type:
                docx_doc = Document(io.BytesIO(file_bytes))
                return "\n".join(p.text for p in docx_doc.paragraphs if p.text.strip())
            else:
                soup = BeautifulSoup(
                    file_bytes.decode("utf-8", errors="replace"), "lxml"
                )
                return soup.get_text(separator="\n", strip=True)
        except CustomException:
            raise
        except Exception as exc:
            logger.error(f"JD text extraction failed for {filename}: {exc}")
            raise CustomException(
                message=RANKING_JD_FILE_PARSE_ERROR,
                status_code=422,
                error_log=str(exc),
            )

    # ------------------------------------------------------------------
    # Private: LLM pipeline steps
    # ------------------------------------------------------------------

    async def _run_jd_analyser(self, jd_text: str) -> JDAnalysisOutput:
        try:
            result: JDAnalysisOutput = await self.llm.with_structured_output(
                JDAnalysisOutput
            ).ainvoke(
                [
                    SystemMessage(content=JD_ANALYSER_PROMPT),
                    HumanMessage(content=f"Analyse this job description:\n\n{jd_text}"),
                ]
            )
            logger.info(
                f"JD Analyser complete: {result.total_lines} lines, "
                f"{result.total_raw_atoms} raw atoms"
            )
            return result
        except Exception as exc:
            logger.error(f"JD Analyser LLM call failed: {exc}")
            raise CustomException(
                message=RANKING_CRITERIA_PARSE_ERROR,
                status_code=500,
                error_log=str(exc),
            )

    async def _run_criteria_generator(
        self, jd_title: str, clean_atoms: List[CleanAtomInput]
    ) -> CriteriaGeneratorOutput:
        atoms_json = json.dumps([a.model_dump() for a in clean_atoms], indent=2)
        human_content = (
            f"### JD Title\n{jd_title}\n\n"
            f"### Cleaned Atoms\n{atoms_json}"
        )
        try:
            result: CriteriaGeneratorOutput = await self.llm.with_structured_output(
                CriteriaGeneratorOutput
            ).ainvoke(
                [
                    SystemMessage(content=CRITERIA_GENERATOR_PROMPT),
                    HumanMessage(content=human_content),
                ]
            )
            logger.info(
                f"Criteria Generator complete: {result.total_criteria} criteria, "
                f"{result.total_atoms} atoms"
            )
            return result
        except Exception as exc:
            logger.error(f"Criteria Generator LLM call failed: {exc}")
            raise CustomException(
                message=RANKING_CRITERIA_PARSE_ERROR,
                status_code=500,
                error_log=str(exc),
            )

    # ------------------------------------------------------------------
    # Private: atom deduplication
    # ------------------------------------------------------------------

    @staticmethod
    def _dedup_atoms(raw_atoms: List[RawAtom]) -> List[CleanAtomInput]:
        seen: dict = {}
        for atom in raw_atoms:
            key = atom.text.strip().lower()
            if key in seen:
                if atom.source_line not in seen[key]["source_lines"]:
                    seen[key]["source_lines"].append(atom.source_line)
            else:
                seen[key] = {
                    "text": atom.text,
                    "source_lines": [atom.source_line],
                    "atom_type": atom.atom_type,
                    "depth": atom.depth,
                    "priority": atom.priority,
                }

        return [
            CleanAtomInput(id=f"CR{i}", **data)
            for i, data in enumerate(seen.values(), start=1)
        ]

    # ------------------------------------------------------------------
    # Private: persistence
    # ------------------------------------------------------------------

    async def _persist_criteria(
        self, jd_id: str, criteria_output: CriteriaGeneratorOutput
    ) -> RankingCriteria:
        criteria_json = json.dumps(criteria_output.model_dump())
        now = datetime.now(timezone.utc)

        async with async_session_factory() as db:
            await db.execute(
                delete(RankingCriteria).where(RankingCriteria.jd_id == jd_id)
            )
            record = RankingCriteria(
                jd_id=jd_id,
                criteria_json=criteria_json,
                generated_at=now,
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)

        logger.info(f"Criteria persisted: jd_id={jd_id} criteria_id={record.id}")
        return record

    # ------------------------------------------------------------------
    # Private: response builders and transformers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_criteria_response(
        jd_id: str,
        record: RankingCriteria,
        criteria_output: CriteriaGeneratorOutput,
    ) -> CriteriaResponse:
        return CriteriaResponse(
            jd_id=jd_id,
            criteria_id=str(record.id),
            generated_at=record.generated_at,
            criteria=[
                CriterionResponse(
                    criterion_name=c.name,
                    description=c.reason_for_weight,
                    weight=round(c.weight / 100, 4),
                    scoring_scale="0-10",
                    explanation=c.description
                )
                for c in criteria_output.criteria
            ],
        )

    @staticmethod
    def _transform_scorer_output(
        candidate_id: str, scorer_dict: dict
    ) -> CandidateScoreResult:
        summary = scorer_dict.get("scoring_summary", {})
        final_score = summary.get("final_score", 0.0)
        mh_matched = summary.get("must_have_matched", 0)
        mh_total = summary.get("must_have_total", 0)
        critical_gaps = scorer_dict.get("critical_gaps", [])
        atom_scores = scorer_dict.get("atom_scores", [])

        def build_category(criterion_id: str) -> RequirementCategory:
            atoms = [
                a for a in atom_scores
                if a.get("criterion_id") == criterion_id and not a.get("display_only", False)
            ]
            if not atoms:
                return RequirementCategory(percentage=0.0, met=0, total=0, items=[])
            items = []
            met = 0
            for a in atoms:
                is_met = a.get("step_6_adjusted_score", 0.0) > 0
                if is_met:
                    met += 1
                items.append(
                    RequirementItem(
                        name=a.get("atom_text", ""),
                        type=a.get("atom_type", ""),
                        priority=(
                            "must-have"
                            if a.get("priority") == "Must-have"
                            else "good-to-have"
                        ),
                        status="met" if is_met else "Not met",
                    )
                )
            pct = (met / len(atoms)) * 100 if atoms else 0.0
            return RequirementCategory(
                percentage=round(pct, 1), met=met, total=len(atoms), items=items
            )

        return CandidateScoreResult(
            candidate_id=candidate_id,
            vacancy={"title": scorer_dict.get("jd_title", "")},
            overall_match={
                "percentage": round(final_score, 2),
                "requirements_met": {"met": mh_matched, "total": mh_total},
            },
            hold={
                "status": "clear" if not critical_gaps else "review",
                "red_flags": {
                    "count": len(critical_gaps),
                    "items": [g.get("atom_text", "") for g in critical_gaps],
                },
            },
            alerts=[],
            requirement_detail=RequirementDetail(
                skills=build_category("C2"),
                experience=build_category("C1"),
                qualifications=build_category("C3"),
            ),
        )
