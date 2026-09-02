"""Public API for dormant server-side browser-session foundations."""

from .models import (
    BrowserSessionRecord,
    IssuedBrowserSession,
    SessionAuthenticationResult,
    SessionDecision,
    SessionValidationError,
)
from .service import (
    SESSION_ABSOLUTE_LIMIT,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_PREFIX,
    SESSION_IDLE_LIMIT,
    SessionRandomPort,
    authenticate_browser_session,
    digest_session_cookie,
    issue_browser_session,
    refreshed_idle_expiry,
)

__all__ = [
    "BrowserSessionRecord",
    "IssuedBrowserSession",
    "SESSION_ABSOLUTE_LIMIT",
    "SESSION_COOKIE_NAME",
    "SESSION_COOKIE_PREFIX",
    "SESSION_IDLE_LIMIT",
    "SessionAuthenticationResult",
    "SessionDecision",
    "SessionRandomPort",
    "SessionValidationError",
    "authenticate_browser_session",
    "digest_session_cookie",
    "issue_browser_session",
    "refreshed_idle_expiry",
]
