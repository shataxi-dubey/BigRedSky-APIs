"""Business logic for the Resume Parser feature."""

import uuid
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import UploadFile
from loguru import logger
from sqlalchemy import desc, select

from app.constants.constants import (
    ALLOWED_RESUME_CONTENT_TYPES,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_PROCESSING,
    MAX_RESUME_FILE_SIZE_BYTES,
)
from app.constants.messages import (
    RESUME_CHUNK_NOT_FOUND,
    RESUME_CHUNK_RETRY_QUEUED,
    RESUME_FILE_TOO_LARGE,
    RESUME_INVALID_FILE_TYPE,
    RESUME_JOB_NOT_RETRYABLE,
    RESUME_PARSE_COMPLETED,
    RESUME_PARSE_NOT_FOUND,
    RESUME_PARSE_RETRY_COMPLETED,
)
from app.core.database import ResumeChunkJob, ResumeParseJob, async_session_factory
from app.core.exceptions.base import CustomException
from app.tasks.celery_main import celery_app

from .helper import extract_text, llm_extract_fields, scrub_pii


class ResumeService:
    """Handles resume upload, synchronous parsing, DB persistence, and Celery chunk dispatch."""

    async def parse_resume(
        self, file: UploadFile, candidate_id: str, form_fields: List[str]
    ) -> Dict[str, Any]:
        if file.content_type not in ALLOWED_RESUME_CONTENT_TYPES:
            raise CustomException(
                message=RESUME_INVALID_FILE_TYPE,
                status_code=422,
                error_log=f"Unsupported content type: {file.content_type}",
            )

        file_bytes = await file.read()
        if len(file_bytes) > MAX_RESUME_FILE_SIZE_BYTES:
            raise CustomException(
                message=RESUME_FILE_TOO_LARGE,
                status_code=413,
                error_log=f"File size {len(file_bytes)} exceeds 10 MB limit",
            )

        async with async_session_factory() as session:
            parse_job = ResumeParseJob(
                candidate_id=candidate_id,
                filename=file.filename or "resume",
                content_type=file.content_type or "",
                file_content=file_bytes,
                form_fields=form_fields,
                status=JOB_STATUS_PROCESSING,
            )
            chunk_job = ResumeChunkJob(
                candidate_id=candidate_id,
                filename=file.filename or "resume",
                content_type=file.content_type or "",
                file_content=file_bytes,
                status=JOB_STATUS_PENDING,
            )
            session.add(parse_job)
            session.add(chunk_job)
            await session.commit()
            await session.refresh(parse_job)
            await session.refresh(chunk_job)
            job_id = parse_job.id
            chunk_job_id = chunk_job.id

        # Run parsing synchronously in the request
        try:
            start = time.time()
            raw_text = extract_text(file_bytes, file.content_type or "")
            elapsed_time = time.time() - start
            logger.info(f"Elapsed time in extracting text from resume {elapsed_time}")

            start = time.time()
            scrubbed_text, pii_entities = scrub_pii(raw_text)
            elapsed_time = time.time() - start
            logger.info(f"Elapsed time in scrubbing PII from resume {elapsed_time}")

            start = time.time()
            parsed_result = llm_extract_fields(scrubbed_text, form_fields)
            elapsed_time = time.time() - start
            logger.info(f"Elapsed time in extracting entities from resume {elapsed_time}")

            async with async_session_factory() as session:
                parse_job = await session.get(ResumeParseJob, job_id)
                parse_job.status = JOB_STATUS_COMPLETED
                parse_job.scrubbed_text = scrubbed_text
                parse_job.pii_entities = pii_entities
                parse_job.parsed_result = parsed_result
                parse_job.updated_at = datetime.now(timezone.utc)
                # Pre-populate scrubbed_text so chunk task skips re-scrubbing
                chunk_job = await session.get(ResumeChunkJob, chunk_job_id)
                chunk_job.scrubbed_text = scrubbed_text
                await session.commit()

        except Exception as exc:
            async with async_session_factory() as session:
                parse_job = await session.get(ResumeParseJob, job_id)
                if parse_job:
                    parse_job.status = JOB_STATUS_FAILED
                    parse_job.error_message = str(exc)
                    parse_job.updated_at = datetime.now(timezone.utc)
                    await session.commit()
            raise CustomException(
                message=str(exc),
                status_code=500,
                error_log=f"Parse failed for candidate_id={candidate_id}: {exc}",
            )

        celery_app.send_task("chunk_resume", args=[str(chunk_job_id)])
        logger.info(
            f"Resume parsed candidate_id={candidate_id} "
            f"job_id={job_id} chunk_job_id={chunk_job_id}"
        )
        return {
            "candidate_id": candidate_id,
            "chunk_job_id": str(chunk_job_id),
            "chunk_status": JOB_STATUS_PENDING,
            "pii_entities": pii_entities,
            "parsed_result": parsed_result,
        }

    async def get_parse_status(self, job_id: str) -> Dict[str, Any]:
        async with async_session_factory() as session:
            try:
                job = await session.get(ResumeParseJob, uuid.UUID(job_id))
            except (ValueError, AttributeError):
                job = None
        if job is None:
            raise CustomException(
                message=RESUME_PARSE_NOT_FOUND.format(job_id=job_id),
                status_code=404,
            )
        return {
            "job_id": str(job.id),
            "candidate_id": job.candidate_id,
            "status": job.status,
            "pii_entities": job.pii_entities,
            "parsed_result": job.parsed_result,
            "error_message": job.error_message,
        }

    async def retry_parse_job(self, job_id: str) -> Dict[str, Any]:
        async with async_session_factory() as session:
            try:
                job = await session.get(ResumeParseJob, uuid.UUID(job_id))
            except (ValueError, AttributeError):
                job = None
        if job is None:
            raise CustomException(
                message=RESUME_PARSE_NOT_FOUND.format(job_id=job_id),
                status_code=404,
            )
        if job.status != JOB_STATUS_FAILED:
            raise CustomException(
                message=RESUME_JOB_NOT_RETRYABLE.format(status=job.status),
                status_code=409,
            )

        file_bytes = job.file_content
        content_type = job.content_type
        form_fields = job.form_fields or []
        candidate_id = job.candidate_id
        parse_uuid = job.id

        async with async_session_factory() as session:
            job = await session.get(ResumeParseJob, parse_uuid)
            job.status = JOB_STATUS_PROCESSING
            job.error_message = None
            await session.commit()

        try:
            raw_text = extract_text(file_bytes, content_type)
            scrubbed_text, pii_entities = scrub_pii(raw_text)
            parsed_result = llm_extract_fields(scrubbed_text, form_fields)

            async with async_session_factory() as session:
                job = await session.get(ResumeParseJob, parse_uuid)
                job.status = JOB_STATUS_COMPLETED
                job.scrubbed_text = scrubbed_text
                job.pii_entities = pii_entities
                job.parsed_result = parsed_result
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()

        except Exception as exc:
            async with async_session_factory() as session:
                job = await session.get(ResumeParseJob, parse_uuid)
                if job:
                    job.status = JOB_STATUS_FAILED
                    job.error_message = str(exc)
                    job.updated_at = datetime.now(timezone.utc)
                    await session.commit()
            raise CustomException(
                message=str(exc),
                status_code=500,
                error_log=f"Retry parse failed for job_id={job_id}: {exc}",
            )

        logger.info(f"Parse job retried job_id={job_id}")
        return {
            "job_id": job_id,
            "candidate_id": candidate_id,
            "status": JOB_STATUS_COMPLETED,
            "pii_entities": pii_entities,
            "parsed_result": parsed_result,
            "message": RESUME_PARSE_RETRY_COMPLETED,
        }

    async def retry_chunk_job(self, candidate_id: str) -> Dict[str, Any]:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ResumeChunkJob)
                .where(ResumeChunkJob.candidate_id == candidate_id)
                .order_by(desc(ResumeChunkJob.created_at))
                .limit(1)
            )
            job = result.scalar_one_or_none()
        if job is None:
            raise CustomException(
                message=RESUME_CHUNK_NOT_FOUND.format(candidate_id=candidate_id),
                status_code=404,
            )
        if job.status != JOB_STATUS_FAILED:
            raise CustomException(
                message=RESUME_JOB_NOT_RETRYABLE.format(status=job.status),
                status_code=409,
            )
        chunk_job_id = str(job.id)
        async with async_session_factory() as session:
            job = await session.get(ResumeChunkJob, job.id)
            job.status = JOB_STATUS_PENDING
            job.error_message = None
            await session.commit()
        celery_app.send_task("chunk_resume", args=[chunk_job_id])
        logger.info(f"Chunk job retried candidate_id={candidate_id} chunk_job_id={chunk_job_id}")
        return {"job_id": chunk_job_id, "status": JOB_STATUS_PENDING, "message": RESUME_CHUNK_RETRY_QUEUED}

    async def get_chunk_status(self, candidate_id: str) -> Dict[str, Any]:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ResumeChunkJob)
                .where(ResumeChunkJob.candidate_id == candidate_id)
                .order_by(desc(ResumeChunkJob.created_at))
                .limit(1)
            )
            job = result.scalar_one_or_none()
        if job is None:
            raise CustomException(
                message=RESUME_CHUNK_NOT_FOUND.format(candidate_id=candidate_id),
                status_code=404,
            )
        return {
            "chunk_job_id": str(job.id),
            "candidate_id": job.candidate_id,
            "status": job.status,
            "chunk_count": job.chunk_count,
            "error_message": job.error_message,
        }
