"""Prompt loader for Contact Draft graph."""

from pathlib import Path

from loguru import logger


def load_prompt(filename: str) -> str:
    """Load a prompt template from a .md file in this directory."""
    path = Path(__file__).parent / filename
    if not path.exists():
        logger.critical(f"Missing prompt file: {path}")
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


DRAFT_PROMPT = load_prompt("draft.md")
