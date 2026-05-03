"""Celery task for async AI candidate scoring."""

import asyncio
import json
import uuid
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
from app.workflows.graphs.ranking.prompts import EVIDENCE_FINDER_PROMPT
from app.apis.v1.ranking.models import EvidenceFinderOutput


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


# ─── Scoring matrices (Steps 2–4) ────────────────────────────────────────────

# Step 2: Max Match lookup tables — (depth, evidence_type) → max_match
# Skill / Experience atoms
_SKILL_EXP_MAX_MATCH: Dict[Tuple[str, str], str] = {
    ("Basic",    "Execution"):  "Full",
    ("Basic",    "Outcome"):    "Full",
    ("Basic",    "Support"):    "Full",
    ("Basic",    "Claim-only"): "Partial",
    ("Standard", "Execution"):  "Full",
    ("Standard", "Outcome"):    "Full",
    ("Standard", "Support"):    "Adjacent",
    ("Standard", "Claim-only"): "Partial",
    ("High",     "Execution"):  "Full",
    ("High",     "Outcome"):    "Full",
    ("High",     "Support"):    "Partial",
    ("High",     "Claim-only"): "No",
}

# Soft skill atoms (stricter — Claim-only is always No)
_SOFT_SKILL_MAX_MATCH: Dict[Tuple[str, str], str] = {
    ("Basic",    "Execution"):  "Full",
    ("Basic",    "Outcome"):    "Full",
    ("Basic",    "Support"):    "Partial",
    ("Basic",    "Claim-only"): "No",
    ("Standard", "Execution"):  "Full",
    ("Standard", "Outcome"):    "Full",
    ("Standard", "Support"):    "Partial",
    ("Standard", "Claim-only"): "No",
    ("High",     "Execution"):  "Full",
    ("High",     "Outcome"):    "Full",
    ("High",     "Support"):    "Partial",
    ("High",     "Claim-only"): "No",
}

# Credential / License / Education atoms (depth irrelevant; Rule 14 already passed)
_CRED_LIC_EDU_MAX_MATCH: Dict[str, str] = {
    "Execution":  "Full",
    "Outcome":    "Full",
    "Support":    "Full",
    "Claim-only": "Full",
}

# Eligibility / Physical atoms
_ELIG_PHYS_MAX_MATCH: Dict[str, str] = {
    "Execution":  "Full",
    "Outcome":    "Full",
    "Support":    "Full",
    "Claim-only": "Full",
}

# Language atoms
_LANG_MAX_MATCH: Dict[str, str] = {
    "Execution":  "Full",
    "Outcome":    "Full",
    "Support":    "Full",
    "Claim-only": "Adjacent",
}

# Step 3 / Step 4a: Intersection matrix — (relation, max_match) → match
_INTERSECTION_MATRIX: Dict[Tuple[str, str], str] = {
    ("Exact",            "Full"):     "Full",
    ("Exact",            "Adjacent"): "Adjacent",
    ("Exact",            "Partial"):  "Partial",
    ("Exact",            "No"):       "No",
    ("Related",          "Full"):     "Adjacent",
    ("Related",          "Adjacent"): "Adjacent",
    ("Related",          "Partial"):  "Partial",
    ("Related",          "No"):       "No",
    ("Same area, vague", "Full"):     "Partial",
    ("Same area, vague", "Adjacent"): "Partial",
    ("Same area, vague", "Partial"):  "Partial",
    ("Same area, vague", "No"):       "No",
    ("Nothing",          "Full"):     "No",
    ("Nothing",          "Adjacent"): "No",
    ("Nothing",          "Partial"):  "No",
    ("Nothing",          "No"):       "No",
}

# Ordinal rank for the Step 4b override comparison
_MATCH_RANK: Dict[str, int] = {"No": 0, "Partial": 1, "Adjacent": 2, "Full": 3}

# Step 5: Match → base score
_BASE_SCORE: Dict[str, float] = {
    "Full":     1.00,
    "Adjacent": 0.75,
    "Partial":  0.55,
    "No":       0.00,
}

# Step 6: Evidence adjustment
_EVIDENCE_ADJUSTMENT: Dict[str, float] = {
    "Execution":       0.00,
    "Outcome":         0.00,
    "Support":        -0.10,
    "Claim-only":     -0.15,
    "Weak inference": -0.25,
    "None":            0.00,
}

# Step 7: Priority weight
_PRIORITY_WEIGHT: Dict[str, int] = {
    "Must-have":    3,
    "Preferred":    2,
    "Good-to-have": 1,
}


# ─── Python scoring helpers (Steps 2–7) ──────────────────────────────────────

def _get_max_match(atom_type: str, depth: Optional[str], evidence_type: str) -> str:
    """Step 2: look up max possible match given atom type, depth, and evidence type."""
    if evidence_type == "None":
        return "No"
    effective_depth = depth or "Standard"
    if atom_type in ("Skill", "Experience"):
        return _SKILL_EXP_MAX_MATCH.get((effective_depth, evidence_type), "No")
    if atom_type == "Soft skill":
        return _SOFT_SKILL_MAX_MATCH.get((effective_depth, evidence_type), "No")
    if atom_type in ("Credential", "License", "Education"):
        return _CRED_LIC_EDU_MAX_MATCH.get(evidence_type, "No")
    if atom_type in ("Eligibility", "Physical"):
        return _ELIG_PHYS_MAX_MATCH.get(evidence_type, "No")
    if atom_type == "Language":
        return _LANG_MAX_MATCH.get(evidence_type, "No")
    return "No"


def _apply_intersection(
    relation: str, max_match: str, evidence_type: str
) -> Tuple[str, str, bool]:
    """Steps 3 + 4a + 4b: intersection matrix then Related+weak-evidence override.

    Returns (intersection_before_override, final_match, override_applied).
    """
    intersection = _INTERSECTION_MATRIX.get((relation, max_match), "No")
    final = intersection
    override = False
    # Step 4b: Related + weak evidence caps at Partial
    if relation == "Related" and evidence_type in ("Support", "Claim-only"):
        if _MATCH_RANK[intersection] > _MATCH_RANK["Partial"]:
            final = "Partial"
            override = True
    return intersection, final, override


def _score_single_atom(atom: dict, ev: dict) -> dict:
    """Compute Steps 2–7 for one atom given its evidence analysis from the LLM."""
    atom_type: str = atom["atom_type"]
    depth: Optional[str] = atom.get("depth")
    priority: str = atom["priority"]
    display_only: bool = atom.get("display_only", False)
    rule_14_result: str = ev["rule_14_result"]
    evidence_type: str = ev["evidence_type"]
    relation: str = ev["relation"]
    priority_weight = _PRIORITY_WEIGHT.get(priority, 1)

    # Rule 14 pre-check: credential/license/education not held → score 0
    if rule_14_result == "does_not_hold":
        return {
            "atom_id": atom["id"],
            "atom_text": atom["text"],
            "atom_type": atom_type,
            "depth": depth,
            "priority": priority,
            "criterion_id": atom["criterion_id"],
            "display_only": display_only,
            "rule_14_applicable": ev["rule_14_applicable"],
            "rule_14_result": rule_14_result,
            "resume_evidence": "",
            "evidence_type": "None",
            "relation": "Nothing",
            "max_match": "No",
            "intersection_match": "No",
            "override_applied": False,
            "final_match": "No",
            "base_score": 0.0,
            # "adjustment": 0.0,
            # "step_6_adjusted_score": 0.0,
            "priority_weight": priority_weight,
            "weighted_atom_score": 0.0,
        }

    max_match = _get_max_match(atom_type, depth, evidence_type)
    intersection_match, final_match, override = _apply_intersection(relation, max_match, evidence_type)
    base_score = _BASE_SCORE[final_match]
    # adjustment = _EVIDENCE_ADJUSTMENT.get(evidence_type, 0.0)
    # adjusted_score = max(0.0, round(base_score + adjustment, 4))
    # weighted_score = round(adjusted_score * priority_weight, 4)
    weighted_score = round(base_score * priority_weight, 4)

    return {
        "atom_id": atom["id"],
        "atom_text": atom["text"],
        "atom_type": atom_type,
        "depth": depth,
        "priority": priority,
        "criterion_id": atom["criterion_id"],
        "display_only": display_only,
        "rule_14_applicable": ev["rule_14_applicable"],
        "rule_14_result": rule_14_result,
        "resume_evidence": ev["resume_evidence"],
        "evidence_type": evidence_type,
        "relation": relation,
        "max_match": max_match,
        "intersection_match": intersection_match,
        "override_applied": override,
        "final_match": final_match,
        "base_score": base_score,
        # "adjustment": adjustment,
        # "step_6_adjusted_score": adjusted_score,
        "priority_weight": priority_weight,
        "weighted_atom_score": weighted_score,
    }


def _compute_rollups(
    atom_scores: List[dict], criteria: List[dict]
) -> Tuple[List[dict], dict, List[dict], List[dict]]:
    """Compute criterion rollups, scoring summary, critical gaps, and good-to-have display."""
    atoms_by_crit: Dict[str, List[dict]] = {}
    for a in atom_scores:
        atoms_by_crit.setdefault(a["criterion_id"], []).append(a)

    criterion_rollups: List[dict] = []
    base_score = 0.0

    for crit in criteria:
        crit_id = crit["id"]
        non_display = [a for a in atoms_by_crit.get(crit_id, []) if not a["display_only"]]

        if non_display:
            # num = sum(a["step_6_adjusted_score"] * a["priority_weight"] for a in non_display)
            num = sum(a["base_score"] * a["priority_weight"] for a in non_display)
            den = sum(a["priority_weight"] for a in non_display)
            crit_score = round(num / den, 6) if den > 0 else 0.0
        else:
            crit_score = 0.0

        contribution = round(crit_score * crit["weight"], 4)
        base_score += contribution
        criterion_rollups.append({
            "criterion_id": crit_id,
            "criterion_name": crit["name"],
            "criterion_weight": crit["weight"],
            "criterion_score": crit_score,
            "contribution_to_base": contribution,
        })

    base_score = round(base_score, 4)

    # Must-have metrics (exclude display_only)
    mh_atoms = [a for a in atom_scores if a["priority"] == "Must-have" and not a["display_only"]]
    mh_total = len(mh_atoms)
    # mh_matched = sum(1 for a in mh_atoms if a["step_6_adjusted_score"] > 0)
    mh_matched = sum(1 for a in mh_atoms if a["base_score"] > 0)
    mh_rate = round(mh_matched / mh_total, 6) if mh_total > 0 else 1.0
    final_score = round(base_score * mh_rate, 4)

    scoring_summary = {
        "base_score": base_score,
        "must_have_total": mh_total,
        "must_have_matched": mh_matched,
        "must_have_match_rate": mh_rate,
        "final_score": final_score,
    }

    critical_gaps = [
        {
            "atom_id": a["atom_id"],
            "atom_text": a["atom_text"],
            "priority": a["priority"],
            "reason": f"No evidence found for: {a['atom_text']}",
        }
        for a in atom_scores
        if a["priority"] == "Must-have" and a["final_match"] == "No" and not a["display_only"]
    ]

    good_to_have_display = [
        {
            "atom_id": a["atom_id"],
            "atom_text": a["atom_text"],
            "match": a["final_match"],
            # "adjusted_score": a["step_6_adjusted_score"],
        }
        for a in atom_scores
        if a["display_only"]
    ]

    return criterion_rollups, scoring_summary, critical_gaps, good_to_have_display


# ─── Scorer: LLM (Step 1) + Python logic (Steps 2–7 + rollup) ────────────────

async def _score_candidate(criteria_dict: dict, resume_text: str) -> Dict[str, Any]:
    """Step 1 via LLM (evidence type + relation); Steps 2–7 and rollup via Python."""
    atoms: List[dict] = criteria_dict.get("cleaned_atoms", [])
    criteria: List[dict] = criteria_dict.get("criteria", [])
    jd_title: str = criteria_dict.get("jd_title", "")

    # Step 1: LLM identifies evidence type and relation per atom
    atoms_input = [
        {
            "id": a["id"],
            "text": a["text"],
            "atom_type": a["atom_type"],
            "depth": a.get("depth"),
            "priority": a["priority"],
            "criterion_id": a["criterion_id"],
        }
        for a in atoms
    ]
    human_content = (
        f"### Atoms\n{json.dumps(atoms_input, indent=2)}\n\n"
        f"### Resume\n{resume_text}"
    )
    llm = _get_llm()
    ev_result: EvidenceFinderOutput = await llm.with_structured_output(
        EvidenceFinderOutput
    ).ainvoke(
        [
            SystemMessage(content=EVIDENCE_FINDER_PROMPT),
            HumanMessage(content=human_content),
        ]
    )

    ev_map: Dict[str, dict] = {r.atom_id: r.model_dump() for r in ev_result.results}

    # Steps 2–7: Python scoring per atom
    atom_scores = [
        _score_single_atom(
            atom,
            ev_map.get(
                atom["id"],
                {
                    "atom_id": atom["id"],
                    "rule_14_applicable": False,
                    "rule_14_result": "not_applicable",
                    "resume_evidence": "",
                    "evidence_type": "None",
                    "relation": "Nothing",
                },
            ),
        )
        for atom in atoms
    ]

    # Rollup and final score
    criterion_rollups, scoring_summary, critical_gaps, good_to_have_display = _compute_rollups(
        atom_scores, criteria
    )

    return {
        "jd_title": jd_title,
        "atom_scores": atom_scores,
        "criterion_rollups": criterion_rollups,
        "scoring_summary": scoring_summary,
        "critical_gaps": critical_gaps,
        "good_to_have_display": good_to_have_display,
    }


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
            start = time.time()
            resume_text = _fetch_candidate_resume(candidate_id)
            logger.info(f" Candidate {candidate_id} Reaume: {resume_text} \n====================\n")
            elapsed_time = time.time() - start
            logger.info(f"Time taken in fetching candidate {candidate_id} resume: {elapsed_time}")
            if not resume_text:
                logger.warning(f"No Qdrant chunks for candidate_id={candidate_id}")
                results.append({
                    "candidate_id": candidate_id,
                    "scorer_output": None,
                    "error": "No resume chunks found in vector store",
                })
                continue
            start = time.time()
            scorer_output = await _score_candidate(criteria_dict, resume_text)
            elapsed_time = time.time() - start
            logger.info(f"Time taken in scoring candidate {candidate_id} resume: {elapsed_time}")
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
