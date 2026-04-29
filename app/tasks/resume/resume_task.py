"""Celery tasks for async resume parsing and vector chunking."""

import asyncio
import io
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import fitz
import numpy as np
from docx import Document
from gliner import GLiNER
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import BaseModel, SecretStr
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from sentence_transformers import SentenceTransformer, SparseEncoder

from app.constants.constants import (
    GLINER_MODEL_NAME,
    GLINER_PII_LABELS,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PROCESSING,
    RESUME_SECTIONS,
)
from app.core.config import settings
from app.core.database import ResumeChunkJob, ResumeParseJob, async_session_factory
from app.tasks.celery_main import celery_app
from app.apis.v1.resume.models import ParsedResume
from app.workflows.graphs.resume.prompts import CHUNK_PROMPT, EXTRACT_PROMPT


# ─── Pydantic schema for LLM-structured chunking output ──────────────────

class SectionChunk(BaseModel):
    section_name: str
    chunk_type: str  # 'technical' | 'non_technical' — assigned by the LLM
    text: str
    skills: List[str] = []
    current_role: Optional[str] = None
    all_roles: List[str] = []
    years_of_experience: Optional[str] = None
    education: Optional[str] = None
    certifications: List[str] = []


class ResumeChunks(BaseModel):
    sections: List[SectionChunk]


# ─── Lazy singletons ──────────────────────────────────────────────────────

_gliner_model: Optional[GLiNER] = None
_dense_model: Optional[SentenceTransformer] = None
_sparse_model: Optional[SparseEncoder] = None
_qdrant_client: Optional[QdrantClient] = None


def _get_gliner() -> GLiNER:
    global _gliner_model
    if _gliner_model is None:
        logger.info(f"Loading GLiNER model: {GLINER_MODEL_NAME}")
        _gliner_model = GLiNER.from_pretrained(GLINER_MODEL_NAME)
    return _gliner_model


def _get_dense_model() -> SentenceTransformer:
    global _dense_model
    if _dense_model is None:
        logger.info(f"Loading dense embedding model: {settings.DENSE_EMBED_MODEL}")
        _dense_model = SentenceTransformer(settings.DENSE_EMBED_MODEL)
    return _dense_model


def _get_sparse_model() -> SparseEncoder:
    global _sparse_model
    if _sparse_model is None:
        logger.info(f"Loading SPLADE model: {settings.SPARSE_EMBED_MODEL}")
        _sparse_model = SparseEncoder(settings.SPARSE_EMBED_MODEL)
    return _sparse_model


def _get_qdrant() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY or None,
        )
    return _qdrant_client


# ─── Pipeline helpers ─────────────────────────────────────────────────────

def _extract_text(file_bytes: bytes, content_type: str) -> str:
    if "pdf" in content_type:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    docx_doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in docx_doc.paragraphs if p.text.strip())


def _scrub_pii(text: str) -> Tuple[str, List[Dict[str, str]]]:
    """Return (scrubbed_text, pii_entities). Entities carry original label + value."""
    model = _get_gliner()
    entities = model.predict_entities(text, GLINER_PII_LABELS, threshold=0.5)
    pii_entities = [{"label": e["label"], "text": e["text"]} for e in entities]
    for entity in sorted(entities, key=lambda e: e["start"], reverse=True):
        placeholder = f"[{entity['label'].upper().replace(' ', '_')}]"
        text = text[: entity["start"]] + placeholder + text[entity["end"] :]
    logger.debug(f"PII scrub: {len(pii_entities)} entities redacted")
    return text, pii_entities


def _llm_extract_fields(
    scrubbed_text: str, form_fields: List[str]
) -> Dict[str, Any]:
    llm = ChatOpenAI(
        model=settings.RESUME_LLM_MODEL,
        api_key=SecretStr(settings.OPENAI_API_KEY),
    )
    fields_hint = (
        f"\nFocus on extracting these fields: {', '.join(form_fields)}."
        if form_fields
        else ""
    )
    result = llm.with_structured_output(ParsedResume).invoke(
        [
            SystemMessage(content=EXTRACT_PROMPT + fields_hint),
            HumanMessage(
                content=f"Extract information from this resume:\n\n{scrubbed_text}"
            ),
        ]
    )
    return result.model_dump()


def _llm_chunk_sections(scrubbed_text: str) -> List[Dict[str, Any]]:
    sections_list = "\n".join(f"- {s}" for s in RESUME_SECTIONS)
    prompt = CHUNK_PROMPT.format(SECTIONS_LIST=sections_list)
    llm = ChatOpenAI(
        model=settings.CHUNK_LLM_MODEL,
        api_key=SecretStr(settings.OPENAI_API_KEY),
    )
    result: ResumeChunks = llm.with_structured_output(ResumeChunks).invoke(
        [
            SystemMessage(content=prompt),
            HumanMessage(
                content=f"Segment the following resume into sections:\n\n{scrubbed_text}"
            ),
        ]
    )
    return [s.model_dump() for s in result.sections]


def _compute_dense(text: str) -> List[float]:
    return _get_dense_model().encode(text, convert_to_numpy=True).tolist()


def _compute_sparse(text: str) -> Tuple[List[int], List[float]]:
    """SPLADE sparse vector: returns (indices, values) of non-zero dimensions."""
    result = _get_sparse_model().encode(text)
    arr = (result.to_dense() if hasattr(result, "to_dense") else result)
    arr = np.asarray(arr).flatten()
    nz = np.nonzero(arr)[0]
    return nz.tolist(), arr[nz].tolist()


def _ensure_qdrant_collection(client: QdrantClient, name: str) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        dim = _get_dense_model().get_embedding_dimension()
        client.create_collection(
            collection_name=name,
            vectors_config={
                "dense": VectorParams(size=dim, distance=Distance.COSINE),
            },
            sparse_vectors_config={"sparse": SparseVectorParams()},
        )
        logger.info(f"Created Qdrant collection '{name}' with dense dim={dim}")


def _embed_and_store(sections: List[Dict[str, Any]], candidate_id: str) -> int:
    qdrant = _get_qdrant()
    collection = settings.QDRANT_COLLECTION_NAME
    _ensure_qdrant_collection(qdrant, collection)
    points = []
    for section in sections:
        text = section["text"]
        dense = _compute_dense(text)
        sparse_idx, sparse_val = _compute_sparse(text)
        point_id = str(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"{candidate_id}:{section['section_name']}")
        )
        points.append(
            PointStruct(
                id=point_id,
                vector={
                    "dense": dense,
                    "sparse": SparseVector(indices=sparse_idx, values=sparse_val),
                },
                payload={
                    "candidate_id": candidate_id,
                    "section_name": section["section_name"],
                    "section_type": section.get("chunk_type", "technical"),
                    "skills": section.get("skills", []),
                    "current_role": section.get("current_role"),
                    "all_roles": section.get("all_roles", []),
                    "years_of_experience": section.get("years_of_experience"),
                    "education": section.get("education"),
                    "certifications": section.get("certifications", []),
                    "text": text,
                },
            )
        )
    if points:
        qdrant.upsert(collection_name=collection, points=points)
        logger.info(f"Stored {len(points)} vectors for candidate_id={candidate_id}")
    return len(points)


# ─── Parse task ───────────────────────────────────────────────────────────

async def _run_parse(job_id: str) -> None:
    async with async_session_factory() as session:
        job: Optional[ResumeParseJob] = await session.get(
            ResumeParseJob, uuid.UUID(job_id)
        )
        if job is None:
            logger.error(f"parse_resume: job not found job_id={job_id}")
            return
        job.status = JOB_STATUS_PROCESSING
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()
        file_bytes = job.file_content
        content_type = job.content_type
        form_fields = job.form_fields or []

    try:
        raw_text = _extract_text(file_bytes, content_type)
        scrubbed_text, pii_entities = _scrub_pii(raw_text)
        logger.info(f"PII data {pii_entities}")
        parsed_result = _llm_extract_fields(scrubbed_text, form_fields)

        async with async_session_factory() as session:
            job = await session.get(ResumeParseJob, uuid.UUID(job_id))
            if job:
                job.status = JOB_STATUS_COMPLETED
                job.scrubbed_text = scrubbed_text
                job.pii_entities = pii_entities
                job.parsed_result = parsed_result
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()
        logger.info(f"parse_resume: completed job_id={job_id}")

    except Exception as exc:
        async with async_session_factory() as session:
            job = await session.get(ResumeParseJob, uuid.UUID(job_id))
            if job:
                job.status = JOB_STATUS_FAILED
                job.error_message = str(exc)
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()
        logger.error(f"parse_resume: failed job_id={job_id} error={exc}")
        raise


@celery_app.task(name="parse_resume", bind=True, max_retries=3)
def parse_resume(self, job_id: str) -> None:
    """Extract text → scrub PII → LLM field extraction. Stores PII + parsed result."""
    try:
        asyncio.run(_run_parse(job_id))
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)
        raise


# ─── Chunk task ───────────────────────────────────────────────────────────

async def _run_chunk(chunk_job_id: str) -> None:
    async with async_session_factory() as session:
        job: Optional[ResumeChunkJob] = await session.get(
            ResumeChunkJob, uuid.UUID(chunk_job_id)
        )
        if job is None:
            logger.error(f"chunk_resume: job not found chunk_job_id={chunk_job_id}")
            return
        job.status = JOB_STATUS_PROCESSING
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()
        file_bytes = job.file_content
        content_type = job.content_type
        candidate_id = job.candidate_id
        scrubbed_text = job.scrubbed_text  # reuse from parse task if already done

    try:
        if not scrubbed_text:
            raw_text = _extract_text(file_bytes, content_type)
            scrubbed_text, _ = _scrub_pii(raw_text)
            async with async_session_factory() as session:
                job = await session.get(ResumeChunkJob, uuid.UUID(chunk_job_id))
                if job:
                    job.scrubbed_text = scrubbed_text
                    await session.commit()
        sections = _llm_chunk_sections(scrubbed_text)
        chunk_count = _embed_and_store(sections, candidate_id)

        async with async_session_factory() as session:
            job = await session.get(ResumeChunkJob, uuid.UUID(chunk_job_id))
            if job:
                job.status = JOB_STATUS_COMPLETED
                job.chunk_count = chunk_count
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()
        logger.info(
            f"chunk_resume: completed chunk_job_id={chunk_job_id} chunks={chunk_count}"
        )

    except Exception as exc:
        async with async_session_factory() as session:
            job = await session.get(ResumeChunkJob, uuid.UUID(chunk_job_id))
            if job:
                job.status = JOB_STATUS_FAILED
                job.error_message = str(exc)
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()
        logger.error(
            f"chunk_resume: failed chunk_job_id={chunk_job_id} error={exc}"
        )
        raise


@celery_app.task(name="chunk_resume", bind=True, max_retries=3)
def chunk_resume(self, chunk_job_id: str) -> None:
    """Extract text → scrub PII → LLM section chunking → SPLADE+Qwen3 embed → Qdrant."""
    try:
        asyncio.run(_run_chunk(chunk_job_id))
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)
        raise
