"""Prompt loader for resume graphs."""

from pathlib import Path

from loguru import logger


def _load(filename: str) -> str:
    path = Path(__file__).parent / filename
    if not path.exists():
        logger.critical(f"Missing prompt file: {path}")
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


EXTRACT_PROMPT = _load("extract.md")
CHUNK_PROMPT = _load("chunk.md")
