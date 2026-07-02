#!/usr/bin/env python3
"""Security headers check for a single URL.

Hits the URL with urllib, evaluates presence and quality of standard
security response headers, writes a JSON summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.request import Request, urlopen
from urllib.error import URLError


EXPECTED_HEADERS = {
    "strict-transport-security": {
        "severity": "HIGH",
        "advice": "Enable HSTS to enforce HTTPS.",
    },
    "content-security-policy": {
        "severity": "HIGH",
        "advice": "Set a Content-Security-Policy to mitigate XSS and injection.",
    },
    "x-content-type-options": {
        "severity": "MEDIUM",
        "advice": "Set 'nosniff' to prevent MIME-type sniffing.",
    },
    "x-frame-options": {
        "severity": "MEDIUM",
        "advice": "Set DENY or SAMEORIGIN to prevent clickjacking.",
    },
    "referrer-policy": {
        "severity": "LOW",
        "advice": "Set a Referrer-Policy to limit referrer leakage.",
    },
    "permissions-policy": {
        "severity": "LOW",
        "advice": "Set a Permissions-Policy to lock down browser features.",
    },
}


def check_url(url: str, timeout: int = 15) -> dict:
    req = Request(url, headers={"User-Agent": "asvs-scanner"})
    findings = []
    error = None
    status_code = None
    headers_seen = {}

    try:
        with urlopen(req, timeout=timeout) as resp:
            status_code = resp.status
            headers_seen = {k.lower(): v for k, v in resp.headers.items()}
    except URLError as exc:
        error = f"URL unreachable: {exc.reason}"
    except Exception as exc:
        error = f"Request failed: {exc}"

    if error:
        return {"url": url, "status_code": None, "error": error, "findings": []}

    for name, spec in EXPECTED_HEADERS.items():
        value = headers_seen.get(name)
        if not value:
            findings.append({
                "header": name,
                "severity": spec["severity"],
                "status": "MISSING",
                "advice": spec["advice"],
            })
        else:
            findings.append({
                "header": name,
                "severity": "INFO",
                "status": "PRESENT",
                "value": value,
            })

    return {
        "url": url,
        "status_code": status_code,
        "error": None,
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--timeout", type=int, default=15)
    args = ap.parse_args()

    result = check_url(args.url, args.timeout)
    with open(args.output, "w") as fh:
        json.dump(result, fh, indent=2)

    if result.get("error"):
        print(f"security-headers: {result['error']}", file=sys.stderr)
        return 2
    missing = [f for f in result["findings"] if f["status"] == "MISSING"]
    print(f"security-headers: {len(missing)} missing headers")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
