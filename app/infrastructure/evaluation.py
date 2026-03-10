"""Response evaluation engine – validates LLM agent outputs for quality metrics."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# Agent name → Pydantic schema class path for validation
SCHEMA_MAP: dict[str, str] = {
    "contact_agent": "app.schemas.contact_agent.ContactAgentOutput",
    "news_agent": "app.schemas.news_agent.NewsAgentOutput",
    "financial_agent": "app.schemas.financial_agent.FinancialAgentOutput",
}


@dataclass
class EvaluationResult:
    """Result of evaluating a single agent response."""
    json_valid: bool = False
    schema_compliant: bool = False
    field_completeness_pct: float = 0.0
    confidence_score_valid: bool = False
    determinism_score: float | None = None
    response_hash: str = ""
    cache_status: str = "miss"  # hit, miss, updated
    latency_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _compute_response_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_json_valid(text: str) -> tuple[bool, dict | None]:
    """Check if text is valid JSON. Returns (is_valid, parsed_data)."""
    try:
        data = json.loads(text)
        return True, data
    except (json.JSONDecodeError, TypeError):
        return False, None


def _check_schema_compliant(agent_name: str, data: dict) -> tuple[bool, list[str]]:
    """Validate data against the expected Pydantic schema.
    Returns (is_compliant, list_of_errors).
    """
    schema_path = SCHEMA_MAP.get(agent_name)
    if not schema_path:
        # No schema defined (e.g. aggregation_agent) – pass by default
        return True, []

    try:
        module_path, class_name = schema_path.rsplit(".", 1)
        import importlib
        module = importlib.import_module(module_path)
        schema_class = getattr(module, class_name)
        schema_class.model_validate(data)
        return True, []
    except Exception as e:
        return False, [str(e)]


def _compute_field_completeness(data: dict, agent_name: str) -> float:
    """Compute % of expected fields that are non-null in the response."""
    expected_fields: dict[str, list[str]] = {
        "contact_agent": [
            "request_id", "agent_name", "status", "data",
            "confidence_score", "source_metadata",
        ],
        "news_agent": [
            "request_id", "agent_name", "status", "data",
            "confidence_score", "source_metadata",
        ],
        "financial_agent": [
            "request_id", "agent_name", "status", "data",
            "confidence_score", "source_metadata",
        ],
        "aggregation_agent": [],  # Free-form
    }
    fields = expected_fields.get(agent_name, [])
    if not fields:
        return 100.0  # No fixed schema expectation

    present = sum(1 for f in fields if data.get(f) is not None)
    return round((present / len(fields)) * 100, 2)


def _check_confidence_score(data: dict) -> bool:
    """Check if confidence_score is within [0, 1]."""
    score = data.get("confidence_score")
    if score is None:
        return False
    try:
        val = float(score)
        return 0.0 <= val <= 1.0
    except (ValueError, TypeError):
        return False


def _compute_determinism_score(
    current_hash: str,
    cached_hash: str | None,
    current_data: dict | None,
    cached_text: str | None,
    cache_status: str,
) -> float | None:
    """Compute determinism score based on comparison with cached response.

    - cache_status == 'hit'     → 100.0 (identical)
    - cache_status == 'updated' → field-level similarity percentage
    - cache_status == 'miss'    → None (no reference to compare)
    """
    if cache_status == "hit":
        return 100.0

    if cache_status == "miss" or cached_text is None:
        return None  # First run, no reference

    # 'updated' – compute field-level similarity
    if current_data is None:
        return 0.0

    try:
        cached_data = json.loads(cached_text)
    except (json.JSONDecodeError, TypeError):
        return 0.0

    return _field_similarity(current_data, cached_data)


def _field_similarity(a: Any, b: Any, depth: int = 0) -> float:
    """Recursively compare two structures and return similarity percentage."""
    if depth > 10:
        return 100.0 if a == b else 0.0

    if type(a) != type(b):
        return 0.0

    if isinstance(a, dict):
        if not a and not b:
            return 100.0
        all_keys = set(a.keys()) | set(b.keys())
        if not all_keys:
            return 100.0
        scores = []
        for key in all_keys:
            if key in a and key in b:
                scores.append(_field_similarity(a[key], b[key], depth + 1))
            else:
                scores.append(0.0)
        return round(sum(scores) / len(scores), 2)

    if isinstance(a, list):
        if not a and not b:
            return 100.0
        max_len = max(len(a), len(b))
        if max_len == 0:
            return 100.0
        scores = []
        for i in range(max_len):
            if i < len(a) and i < len(b):
                scores.append(_field_similarity(a[i], b[i], depth + 1))
            else:
                scores.append(0.0)
        return round(sum(scores) / len(scores), 2)

    # Scalar comparison
    return 100.0 if a == b else 0.0


def evaluate_response(
    agent_name: str,
    response_text: str,
    cache_status: str = "miss",
    cached_response_text: str | None = None,
    cached_response_hash: str | None = None,
    latency_ms: int | None = None,
) -> EvaluationResult:
    """Run all evaluation metrics on an agent response.

    Args:
        agent_name: Which agent produced this response.
        response_text: The raw response text.
        cache_status: 'hit', 'miss', or 'updated'.
        cached_response_text: Previous cached response for determinism comparison.
        cached_response_hash: Hash of the cached response.
        latency_ms: How long the agent took.

    Returns:
        EvaluationResult with all metrics populated.
    """
    result = EvaluationResult()
    result.cache_status = cache_status
    result.latency_ms = latency_ms
    result.response_hash = _compute_response_hash(response_text)

    details: dict[str, Any] = {}

    # 1. JSON validity
    json_ok, parsed = _check_json_valid(response_text)
    result.json_valid = json_ok
    details["json_valid"] = json_ok

    if not json_ok:
        details["json_error"] = "Response is not valid JSON"
        result.details = details
        return result

    # 2. Schema compliance
    schema_ok, schema_errors = _check_schema_compliant(agent_name, parsed)
    result.schema_compliant = schema_ok
    details["schema_compliant"] = schema_ok
    if schema_errors:
        details["schema_errors"] = schema_errors[:3]  # Keep first 3

    # 3. Field completeness
    completeness = _compute_field_completeness(parsed, agent_name)
    result.field_completeness_pct = completeness
    details["field_completeness_pct"] = completeness

    # 4. Confidence score validity
    conf_ok = _check_confidence_score(parsed)
    result.confidence_score_valid = conf_ok
    details["confidence_score_valid"] = conf_ok
    details["confidence_score_value"] = parsed.get("confidence_score")

    # 5. Determinism score
    det = _compute_determinism_score(
        current_hash=result.response_hash,
        cached_hash=cached_response_hash,
        current_data=parsed,
        cached_text=cached_response_text,
        cache_status=cache_status,
    )
    result.determinism_score = det
    details["determinism_score"] = det
    details["cache_status"] = cache_status

    result.details = details
    return result
