"""Contracts and constants for browser authentication."""

from __future__ import annotations

from typing import NotRequired, TypedDict


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleIdentityPayload(TypedDict):
    """Claims consumed from a Google Workspace ID token."""

    email: NotRequired[str]
    hd: NotRequired[str]
