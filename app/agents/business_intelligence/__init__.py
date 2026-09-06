"""Business Intelligence service package (vendored under app/agents/).

Available through ``app.agents.business_intelligence`` to the router and as a
top-level package to compatibility shims. The service layer orchestrates the
caller-JWT-scoped repositories in ``app/repositories/business_intelligence.py``.
"""

from business_intelligence.service import (
    chat_reply,
    create_report,
    get_recommendation,
    overview,
    run_agent,
)

__all__ = [
    "chat_reply",
    "create_report",
    "get_recommendation",
    "overview",
    "run_agent",
]
