"""Content-team API auth dependency (defense-in-depth for standalone runs).

The gateway already enforces Bearer auth on ``/api/*`` via middleware. This
dependency ensures the content_team router also authenticates when run as a
standalone uvicorn app (``hermes.content_team.app:app``), sharing the same
``HERMES_API_TOKEN`` (fallback to legacy ``OPENCLAW_GATEWAY_TOKEN``).

No token configured → auth disabled (dev mode), matching workbench semantics.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency enforcing Bearer auth on content_team routes."""
    from hermes.config import get_settings

    settings = get_settings()
    expected = getattr(settings, "hermes_api_token", None) or getattr(
        settings, "openclaw_gateway_token", None
    )
    if not expected:
        return  # dev mode: no token configured
    if authorization and authorization.startswith("Bearer "):
        if secrets.compare_digest(authorization[7:], expected):
            return
    raise HTTPException(status_code=401, detail="unauthorized")
