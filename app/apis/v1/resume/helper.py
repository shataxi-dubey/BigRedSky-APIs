"""Utility functions for the Resume Summary pipeline."""

import io
from typing import Tuple

import aioboto3
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from docx import Document
from gliner import GLiNER
from loguru import logger

from app import settings
from app.constants.constants import SUMMARY_PII_LABELS, SUMMARY_PII_PLACEHOLDERS
from app.core.exceptions.base import CustomException
from app.constants.messages import RESUME_PARSE_ERROR, RESUME_S3_FETCH_ERROR


async def fetch_resume_from_s3(s3_path: str) -> Tuple[bytes, str]:
    """Download a file from S3 and return (bytes, filename)."""
    session = aioboto3.Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )
    filename = s3_path.split("/")[-1]
    try:
        async with session.client("s3") as s3:
            response = await s3.get_object(Bucket=settings.AWS_S3_BUCKET, Key=s3_path)
            body = await response["Body"].read()
        return body, filename
    except Exception as exc:
        logger.error(f"S3 fetch failed for {s3_path}: {exc}")
        raise CustomException(message=RESUME_S3_FETCH_ERROR, status_code=502, error_log=str(exc))


def parse_resume_file(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from a PDF or DOCX file."""
    ext = filename.rsplit(".", 1)[-1].lower()
    try:
        if ext == "pdf":
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            return "\n".join(page.get_text() for page in doc)
        elif ext in ("docx", "doc"):
            doc = Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        else:
            raise CustomException(
                message=f"Unsupported file type: {ext}", status_code=400, error_log=f"ext={ext}"
            )
    except CustomException:
        raise
    except Exception as exc:
        logger.error(f"Failed to parse resume file {filename}: {exc}")
        raise CustomException(message=RESUME_PARSE_ERROR, status_code=422, error_log=str(exc))


def scrub_pii(text: str) -> str:
    """Replace PII entities in text with neutral placeholders using GLiNER."""
    try:
        model = GLiNER.from_pretrained(settings.GLINER_MODEL)
        entities = model.predict_entities(text, SUMMARY_PII_LABELS, threshold=0.5)
        # Sort by start position descending so replacements don't shift offsets
        entities_sorted = sorted(entities, key=lambda e: e["start"], reverse=True)
        for ent in entities_sorted:
            placeholder = SUMMARY_PII_PLACEHOLDERS.get(ent["label"], f"[{ent['label'].upper()}]")
            text = text[: ent["start"]] + placeholder + text[ent["end"] :]
        return text
    except Exception as exc:
        # PII scrubbing failure is non-fatal only if the error is transient;
        # we raise to keep the pipeline safe rather than silently forwarding raw PII.
        logger.error(f"GLiNER PII scrubbing failed: {exc}")
        raise CustomException(
            message="PII scrubbing failed. Cannot proceed without sanitising resume text.",
            status_code=500,
            error_log=str(exc),
        )


def html_to_text(html: str) -> str:
    """Strip HTML tags and return clean plain text."""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator="\n", strip=True)
