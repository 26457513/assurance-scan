#!/usr/bin/env python3
"""Upload one canonical GitHub Actions bundle using an OIDC JWT read from stdin."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.infrastructure.github_oidc_upload import StdlibGithubOidcUploadTransport
from app.modules.atomic.ingestion.github_oidc_upload_client import (
    GithubUploadConfig,
    GithubUploadError,
    load_bundle,
    read_oidc_jwt,
    upload_once,
)


RETRYABLE_EXIT = 75


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Assurance Scan public base URL")
    parser.add_argument("--bundle", default="/bundle", help="read-only v2 bundle directory")
    args = parser.parse_args()
    try:
        token = read_oidc_jwt(sys.stdin.buffer)
        bundle = load_bundle(Path(args.bundle))
        result = upload_once(
            bundle,
            GithubUploadConfig(base_url=args.url, oidc_jwt=token),
            transport=StdlibGithubOidcUploadTransport(),
        )
    except GithubUploadError as exc:
        print(f"assurance-scan upload failed ({exc.code})", file=sys.stderr)
        return RETRYABLE_EXIT if exc.retryable else 1
    if result.status in {200, 201, 202}:
        print("assurance-scan upload accepted")
        return 0
    print(f"assurance-scan upload rejected ({result.code})", file=sys.stderr)
    return RETRYABLE_EXIT if result.retryable else 1


if __name__ == "__main__":
    raise SystemExit(main())
