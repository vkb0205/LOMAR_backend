"""Business Intelligence service package (vendored under app/agents/).

Imported as a top-level ``business_intelligence`` package by the router and the
``app.services.business_intelligence`` shim. The service layer orchestrates the
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
