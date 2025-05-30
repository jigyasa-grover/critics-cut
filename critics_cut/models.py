"""
Critic's Cut v2 — Pydantic Models
===================================
Structured data models used across tools and guardrails.
"""

from pydantic import BaseModel, Field
from enum import Enum


class WatchlistAction(str, Enum):
    """Valid watchlist operations."""
    ADD = "add"
    REMOVE = "remove"
    LIST = "list"


class WatchlistResult(BaseModel):
    """Structured result from a watchlist operation."""
    status: str = Field(description="Operation result: added, removed, listed, error")
    title: str | None = Field(default=None, description="Movie title acted upon")
    watchlist: list[str] = Field(default_factory=list, description="Current watchlist contents")
    count: int = Field(default=0, description="Number of items in watchlist")
    message: str | None = Field(default=None, description="Human-readable detail")


class GuardrailResult(BaseModel):
    """Outcome of a guardrail check."""
    passed: bool = Field(description="Whether the check passed")
    reason: str | None = Field(default=None, description="Why it was blocked, if applicable")
    patterns_matched: list[str] = Field(default_factory=list, description="Patterns that triggered")
