"""
Critic's Cut v2 — Safety Guardrails
=====================================
ADK callbacks that intercept the agent pipeline at multiple levels:

  before_model_callback  → blocks prompt injection (root agent)
  after_model_callback   → redacts PII from responses (root agent)
  before_tool_callback   → validates tool inputs (WatchlistAgent)

These provide defense-in-depth: model-level, output-level, and tool-level.
"""

import re
import logging
from typing import Optional, Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse, LlmRequest
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from .models import GuardrailResult

logger = logging.getLogger(__name__)

# Prompt injection patterns (deterministic, zero external deps)

_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|directives|prompts)",
        r"reveal\s+(your\s+)?(system|initial)\s+(prompt|instruction)",
        r"you\s+are\s+now\s+in\s+.*mode",
        r"override\s+(system|safety)",
        r"act\s+as\s+(an?\s+)?(unrestricted|unfiltered|jailbroken)",
    ]
]

# PII patterns for output redaction

_PII_PATTERNS: dict[str, re.Pattern] = {
    "[EMAIL REDACTED]": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "[PHONE REDACTED]": re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "[SSN REDACTED]": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}

# Watchlist constraints

MAX_WATCHLIST_SIZE = 50
MAX_TITLE_LENGTH = 200


def _extract_last_user_text(llm_request: LlmRequest) -> str:
    """Pull the text of the most recent user message from the LLM request."""
    if llm_request.contents and llm_request.contents[-1].role == "user":
        parts = llm_request.contents[-1].parts or []
        return " ".join(p.text for p in parts if p.text)
    return ""


# CALLBACK 1: before_model_callback (root agent)
def input_guardrail(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Block prompt-injection attempts before they reach the LLM.

    Returns an LlmResponse to short-circuit the call when a threat is
    detected, or None to let the request proceed normally.
    """
    text = _extract_last_user_text(llm_request)
    matched = [p.pattern for p in _INJECTION_PATTERNS if p.search(text)]

    if matched:
        result = GuardrailResult(passed=False, reason="prompt_injection", patterns_matched=matched)
        logger.warning("Input guardrail BLOCKED: %s", result.model_dump_json())
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=(
                    "I can't process that request. "
                    "If you have a question about movies or TV shows, I'm happy to help."
                ))],
            )
        )
    return None


# CALLBACK 2: after_model_callback (root agent)
def output_guardrail(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> Optional[LlmResponse]:
    """Redact PII from the model's response before it reaches the user."""
    if not llm_response.content or not llm_response.content.parts:
        return None

    modified = False
    new_parts: list[types.Part] = []

    for part in llm_response.content.parts:
        text = part.text
        if not text:
            new_parts.append(part)
            continue
        for replacement, pattern in _PII_PATTERNS.items():
            if pattern.search(text):
                text = pattern.sub(replacement, text)
                modified = True
        new_parts.append(types.Part(text=text))

    if modified:
        logger.info("Output guardrail — PII redacted from response")
        return LlmResponse(content=types.Content(role="model", parts=new_parts))
    return None


# CALLBACK 3: before_tool_callback (WatchlistAgent)
def watchlist_tool_guardrail(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> Optional[dict]:
    """Validate watchlist tool arguments before execution.

    - Enforces max title length and watchlist size limits.
    - Sanitizes title input (strip whitespace).
    - Returns a dict to skip the tool call if validation fails;
      returns None to proceed normally.
    """
    if tool.name != "manage_watchlist":
        return None

    title = args.get("title", "")
    action = args.get("action", "")

    # Sanitize title — strip whitespace
    if title:
        args["title"] = title.strip()

    # Title length check
    if title and len(title) > MAX_TITLE_LENGTH:
        logger.warning("Tool guardrail — title too long: %d chars", len(title))
        return {
            "status": "error",
            "message": f"Title must be under {MAX_TITLE_LENGTH} characters.",
        }

    # Watchlist size check on add
    if action == "add":
        current = tool_context.state.get("user_watchlist", [])
        if len(current) >= MAX_WATCHLIST_SIZE:
            logger.warning("Tool guardrail — watchlist full: %d items", len(current))
            return {
                "status": "error",
                "message": f"Watchlist is full ({MAX_WATCHLIST_SIZE} movies max). Remove one first.",
            }

    logger.debug("Tool guardrail — passed for %s(%s)", tool.name, action)
    return None
