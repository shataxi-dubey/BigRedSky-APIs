"""Parsing helpers shared between the Resume service and Celery chunk task."""

import io
from typing import Any, Dict, List, Optional, Tuple

import fitz
from docx import Document
from gliner import GLiNER
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import SecretStr

from app.constants.constants import GLINER_MODEL_NAME, GLINER_PII_LABELS
from app.core.config import settings
from app.workflows.graphs.resume.prompts import EXTRACT_PROMPT
from app.core.langfuse_handler import langfuse_handler

_gliner_model: Optional[GLiNER] = None


def _get_gliner() -> GLiNER:
    global _gliner_model
    if _gliner_model is None:
        logger.info(f"Loading GLiNER model: {GLINER_MODEL_NAME}")
        _gliner_model = GLiNER.from_pretrained(GLINER_MODEL_NAME)
    return _gliner_model


def extract_text(file_bytes: bytes, content_type: str) -> str:
    if "pdf" in content_type:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    docx_doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in docx_doc.paragraphs if p.text.strip())


def scrub_pii(text: str) -> Tuple[str, List[Dict[str, str]]]:
    """Return (scrubbed_text, pii_entities). Entities carry original label + value."""
    model = _get_gliner()
    entities = model.predict_entities(text, GLINER_PII_LABELS, threshold=0.5)
    pii_entities = [{"label": e["label"], "text": e["text"]} for e in entities]
    for entity in sorted(entities, key=lambda e: e["start"], reverse=True):
        placeholder = f"[{entity['label'].upper().replace(' ', '_')}]"
        text = text[: entity["start"]] + placeholder + text[entity["end"] :]
    logger.debug(f"PII scrub: {len(pii_entities)} entities redacted")
    return text, pii_entities


def llm_extract_fields(scrubbed_text: str, form_fields: List[str]) -> Dict[str, Any]:
    from app.apis.v1.resume.models import ParsedResume

    llm = ChatOpenAI(
        model=settings.RESUME_LLM_MODEL,
        api_key=SecretStr(settings.OPENAI_API_KEY),
        callbacks=[langfuse_handler]
    )
    fields_hint = (
        f"\nFocus on extracting these fields: {', '.join(form_fields)}."
        if form_fields
        else ""
    )
    result = llm.with_structured_output(ParsedResume).invoke(
        [
            SystemMessage(content=EXTRACT_PROMPT + fields_hint),
            HumanMessage(content=f"Extract information from this resume:\n\n{scrubbed_text}"),
        ]
    )
    return result.model_dump()
