"""Pydantic models for the AI Ranking feature."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ─── Internal LLM schemas — Prompt 1: JD Analyser ────────────────────────────

class JDLine(BaseModel):
    id: str
    section: str
    text: str


class RawAtom(BaseModel):
    id: str
    text: str
    source_line: str
    atom_type: Literal[
        "Skill", "Experience", "Credential", "License",
        "Education", "Eligibility", "Soft skill", "Language", "Physical"
    ]
    depth: Optional[Literal["Basic", "Standard", "High"]] = None
    priority: Literal["Must-have", "Preferred", "Good-to-have"]


class JDAnalysisOutput(BaseModel):
    jd_title: str
    company: Optional[str] = None
    lines: List[JDLine]
    raw_atoms: List[RawAtom]
    total_lines: int
    total_raw_atoms: int


# ─── Internal: dedup step output (input to Prompt 2) ─────────────────────────

class CleanAtomInput(BaseModel):
    id: str
    text: str
    source_lines: List[str]
    atom_type: Literal[
        "Skill", "Experience", "Credential", "License",
        "Education", "Eligibility", "Soft skill", "Language", "Physical"
    ]
    depth: Optional[Literal["Basic", "Standard", "High"]] = None
    priority: Literal["Must-have", "Preferred", "Good-to-have"]


# ─── Internal LLM schemas — Prompt 2: Criteria Generator ─────────────────────

class CleanedAtom(BaseModel):
    id: str
    text: str
    source_lines: List[str]
    atom_type: Literal[
        "Skill", "Experience", "Credential", "License",
        "Education", "Eligibility", "Soft skill", "Language", "Physical"
    ]
    depth: Optional[Literal["Basic", "Standard", "High"]] = None
    priority: Literal["Must-have", "Preferred", "Good-to-have"]
    criterion_id: str
    display_only: bool


class Criterion(BaseModel):
    id: str
    name: Literal[
        "Experience",
        "Skills",
        "Qualifications",
        "Tools & Technologies",
        "Responsibilities & Ownership",
        "Process & Methodology",
        "Eligibility & Logistics",
    ]
    weight: int
    atom_ids: List[str]
    reason_for_weight: str
    description: str= Field(description="4-5 words explaining what this criteria covers")


class CriteriaGeneratorOutput(BaseModel):
    jd_title: str
    cleaned_atoms: List[CleanedAtom]
    criteria: List[Criterion]
    total_atoms: int
    total_criteria: int
    must_have_count: int
    preferred_count: int
    good_to_have_count: int


# ─── Internal LLM schemas — Evidence-Relation Finder ─────────────────────────

class AtomEvidenceResult(BaseModel):
    atom_id: str
    rule_14_applicable: bool
    rule_14_result: Literal["holds", "does_not_hold", "not_applicable"]
    resume_evidence: str
    evidence_type: Literal["Execution", "Outcome", "Support", "Claim-only", "None"]
    relation: Literal["Exact", "Related", "Same area, vague", "Nothing"]


class EvidenceFinderOutput(BaseModel):
    results: List[AtomEvidenceResult]


# ─── API request models ───────────────────────────────────────────────────────

class ScoreRequest(BaseModel):
    jd_id: str = Field(description="Criteria are fetched from DB via this ID.")
    candidate_ids: List[str] = Field(description="Candidate UUIDs to score.")


# ─── API response models ──────────────────────────────────────────────────────

class CriterionResponse(BaseModel):
    criterion_name: str
    description: str
    weight: float
    scoring_scale: str = "0-10"
    explanation:str


class CriteriaResponse(BaseModel):
    jd_id: str
    criteria_id: str
    generated_at: datetime
    criteria: List[CriterionResponse]


class ScoreJobResponse(BaseModel):
    job_id: str
    status: str
    candidate_count: int


class RequirementItem(BaseModel):
    name: str
    type: str
    priority: str
    status: str


class RequirementCategory(BaseModel):
    percentage: float
    met: int
    total: int
    items: List[RequirementItem]


class RequirementDetail(BaseModel):
    skills: RequirementCategory
    experience: RequirementCategory
    qualifications: RequirementCategory


class CandidateScoreResult(BaseModel):
    candidate_id: str
    vacancy: Dict[str, Any]
    overall_match: Dict[str, Any]
    hold: Dict[str, Any]
    alerts: List[str]
    requirement_detail: RequirementDetail


class ScoreJobStatusResponse(BaseModel):
    job_id: str
    jd_id: str
    status: str
    completed_at: Optional[datetime] = None
    candidate_count: int
    results: Optional[List[CandidateScoreResult]] = None
