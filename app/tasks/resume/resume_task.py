"""Celery task for async resume vector chunking."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel, SecretStr
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from fastembed import SparseTextEmbedding

from app.constants.constants import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PROCESSING,
    RESUME_SECTIONS,
)
from app.core.config import settings
from app.core.database import ResumeChunkJob, async_session_factory
from app.tasks.celery_main import celery_app
from app.apis.v1.resume.helper import extract_text, scrub_pii
from app.workflows.graphs.resume.prompts import CHUNK_PROMPT
from app.core.langfuse_handler import langfuse_handler


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

_nebius_client: Optional[AsyncOpenAI] = None
_sparse_model: Optional[SparseTextEmbedding] = None
_qdrant_client: Optional[QdrantClient] = None


def _get_nebius_client() -> AsyncOpenAI:
    global _nebius_client
    if _nebius_client is None:
        _nebius_client = AsyncOpenAI(
            api_key=settings.NEBIUS_API_KEY,
            base_url=settings.NEBIUS_BASE_URL,
        )
    return _nebius_client


def _get_sparse_model() -> SparseTextEmbedding:
    global _sparse_model
    if _sparse_model is None:
        logger.info(f"Loading SPLADE model: {settings.SPARSE_EMBED_MODEL}")
        _sparse_model = SparseTextEmbedding(model_name=settings.SPARSE_EMBED_MODEL)
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

def _llm_chunk_sections(scrubbed_text: str) -> List[Dict[str, Any]]:
    sections_list = "\n".join(f"- {s}" for s in RESUME_SECTIONS)
    prompt = CHUNK_PROMPT.format(SECTIONS_LIST=sections_list)
    llm = ChatOpenAI(
        model=settings.CHUNK_LLM_MODEL,
        api_key=SecretStr(settings.OPENAI_API_KEY),
        callbacks=[langfuse_handler]
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


async def _compute_dense(text: str) -> List[float]:
    response = await _get_nebius_client().embeddings.create(
        model=settings.DENSE_EMBED_MODEL,
        input=text,
    )
    return response.data[0].embedding


def _compute_sparse(text: str) -> Tuple[List[int], List[float]]:
    result = next(_get_sparse_model().embed([text]))
    return result.indices.tolist(), result.values.tolist()


def _ensure_qdrant_collection(client: QdrantClient, name: str) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config={
                "dense": VectorParams(size=settings.DENSE_EMBED_DIM, distance=Distance.COSINE),
            },
            sparse_vectors_config={"sparse": SparseVectorParams()},
        )
        logger.info(f"Created Qdrant collection '{name}' with dense dim={settings.DENSE_EMBED_DIM}")


async def _embed_and_store(sections: List[Dict[str, Any]], candidate_id: str) -> int:
    qdrant = _get_qdrant()
    collection = settings.QDRANT_COLLECTION_NAME
    _ensure_qdrant_collection(qdrant, collection)
    points = []
    for section in sections:
        text = section["text"]
        dense = await _compute_dense(text)
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
        scrubbed_text = job.scrubbed_text  # pre-populated by the sync parse step

    try:
        if not scrubbed_text:
            raw_text = extract_text(file_bytes, content_type)
            scrubbed_text, _ = scrub_pii(raw_text)
            async with async_session_factory() as session:
                job = await session.get(ResumeChunkJob, uuid.UUID(chunk_job_id))
                if job:
                    job.scrubbed_text = scrubbed_text
                    await session.commit()
        sections = _llm_chunk_sections(scrubbed_text)
        chunk_resume = ""
        for s in sections:
            chunk_resume += '\n'+'='*8+"\n" + s["section_name"] + ':'+ s["text"] + '\n=========\n'
        logger.info(f"The output chunked is {chunk_resume}")
        chunk_count = await _embed_and_store(sections, candidate_id)

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
    """LLM section chunking → SPLADE + dense embed → Qdrant upsert."""
    try:
        asyncio.run(_run_chunk(chunk_job_id))
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=30)
        raise
