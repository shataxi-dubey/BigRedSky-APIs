"""Prompt loader for AI Ranking graphs."""

from pathlib import Path

from loguru import logger


def load_prompt(filename: str) -> str:
    """Load a prompt template from a .md file in this directory."""
    path = Path(__file__).parent / filename
    if not path.exists():
        logger.critical(f"Missing prompt file: {path}")
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


JD_ANALYSER_PROMPT = load_prompt("jd_analyser.md")
CRITERIA_GENERATOR_PROMPT = load_prompt("criteria_generator.md")
SCORER_PROMPT = load_prompt("scorer.md")
EVIDENCE_FINDER_PROMPT = load_prompt("evidence-relation-finder.md")
