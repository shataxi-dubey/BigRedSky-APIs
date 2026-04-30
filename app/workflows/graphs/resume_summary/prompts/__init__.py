"""Prompt loader for Resume Summary."""

from pathlib import Path

from loguru import logger


def load_prompt(filename: str) -> str:
    path = Path(__file__).parent / filename
    if not path.exists():
        logger.critical(f"Missing prompt file: {path}")
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


SUMMARY_PROMPT = load_prompt("summary.md")
