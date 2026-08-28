"""Replaceable transport and timing ports for the upload client."""
from __future__ import annotations

from typing import Protocol

from .models import HttpResponse, UploadBundle, UploadClientConfig


class UploadTransportPort(Protocol):
    def post_multipart(
        self,
        url: str,
        config: UploadClientConfig,
        bundle: UploadBundle,
    ) -> HttpResponse: ...

    def get_status(
        self,
        url: str,
        config: UploadClientConfig,
    ) -> HttpResponse: ...


class RetryClockPort(Protocol):
    def sleep(self, seconds: float) -> None: ...


__all__ = ["RetryClockPort", "UploadTransportPort"]
