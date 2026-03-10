"""Post-processing normalization for agent outputs.

Applies deterministic rules to clamp and standardize LLM-generated
scores so they are consistent across runs even when the LLM varies
slightly.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ── Title → decision_maker_score mapping ──
_TITLE_TIERS: list[tuple[list[str], tuple[int, int]]] = [
    (["ceo", "cto", "cfo", "coo", "cio", "ciso", "cmo", "cpo", "chief"], (90, 100)),
    (["svp", "senior vice president", "evp", "executive vice president", "vp", "vice president"], (70, 89)),
    (["director", "head of"], (50, 69)),
    (["senior manager", "manager"], (30, 49)),
]


def _score_title(title: str) -> int:
    """Deterministic decision-maker score based on title keywords."""
    t = title.lower().strip()
    for keywords, (lo, hi) in _TITLE_TIERS:
        for kw in keywords:
            if kw in t:
                return (lo + hi) // 2  # midpoint of range
    return 15  # default for unknown titles


def _clamp(value: int | float, lo: int | float, hi: int | float) -> int | float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, value))


def normalize_contact_output(raw_text: str) -> str:
    """Normalize contact agent JSON output with deterministic scoring."""
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return raw_text  # Not JSON, return as-is

    # Normalize top-level confidence
    if "confidence_score" in data:
        data["confidence_score"] = round(_clamp(float(data["confidence_score"]), 0.0, 1.0), 2)

    # Normalize per-contact scores
    contacts = data.get("data", {}).get("contacts_found", [])
    for contact in contacts:
        # Override decision_maker_score based on title
        title = contact.get("title", "")
        if title:
            contact["decision_maker_score"] = _score_title(title)

        # Clamp quality score
        contact["contact_quality_score"] = int(_clamp(
            contact.get("contact_quality_score", 0), 0, 100
        ))

        # Clamp confidence
        contact["confidence_score"] = round(_clamp(
            float(contact.get("confidence_score", 0)), 0.0, 1.0
        ), 2)

    return json.dumps(data, indent=None)


def normalize_news_output(raw_text: str) -> str:
    """Normalize news agent JSON output with clamped scores."""
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return raw_text

    if "confidence_score" in data:
        data["confidence_score"] = round(_clamp(float(data["confidence_score"]), 0.0, 1.0), 2)

    news_data = data.get("data", {})
    if "intent_score" in news_data:
        news_data["intent_score"] = int(_clamp(news_data["intent_score"], 0, 100))
    if "overall_sentiment_score" in news_data:
        news_data["overall_sentiment_score"] = int(_clamp(news_data["overall_sentiment_score"], 0, 100))

    for article in news_data.get("recent_news", []):
        article["impact_score"] = int(_clamp(article.get("impact_score", 0), 0, 100))
        # Normalize sentiment to allowed values
        valid_sentiments = {"positive", "negative", "neutral", "mixed"}
        if article.get("sentiment", "").lower() not in valid_sentiments:
            article["sentiment"] = "neutral"

    return json.dumps(data, indent=None)


def normalize_financial_output(raw_text: str) -> str:
    """Normalize financial agent JSON output with clamped scores."""
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return raw_text

    if "confidence_score" in data:
        data["confidence_score"] = round(_clamp(float(data["confidence_score"]), 0.0, 1.0), 2)

    fin_data = data.get("data", {})
    for key in ("firmographic_score", "growth_score", "industry_match_score"):
        if key in fin_data:
            fin_data[key] = int(_clamp(fin_data[key], 0, 100))

    return json.dumps(data, indent=None)


# Map agent_name → normalizer function
NORMALIZERS = {
    "contact_agent": normalize_contact_output,
    "news_agent": normalize_news_output,
    "financial_agent": normalize_financial_output,
}


def normalize_output(agent_name: str, raw_text: str) -> str:
    """Apply the appropriate normalizer for the given agent.

    Returns the original text unchanged if no normalizer exists.
    """
    normalizer = NORMALIZERS.get(agent_name)
    if normalizer:
        try:
            return normalizer(raw_text)
        except Exception as e:
            logger.warning("Normalization failed for %s: %s", agent_name, e)
    return raw_text
