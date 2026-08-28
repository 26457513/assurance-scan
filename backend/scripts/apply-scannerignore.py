#!/usr/bin/env python3
"""Apply .scannerignore patterns to a scanner's output, in place.

Usage:
    apply-scannerignore.py \
        --scanner-ignore .scannerignore \
        --scanner {semgrep|gitleaks|trivy-config|trivy-fs|syft|grype} \
        --output <path>

Behaviour:
- Reads the scanner's output file
- Removes findings whose target path matches any .scannerignore pattern
- Rewrites the file in place
- Prints a summary of how many findings were removed

Note: dependency scanners (trivy-fs, syft, grype) are intentionally NOT
filtered by default — they need full filesystem coverage to detect vulnerable
dependencies in node_modules etc. This script will refuse to filter them
unless run with --force.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path


# Scanners that depend on full filesystem coverage for correctness.
DEPENDENCY_SCANNERS = {"trivy-fs", "syft", "grype", "osv-scanner"}


def load_patterns(scanner_ignore: Path) -> list[str]:
    """Parse .scannerignore into a list of glob patterns."""
    if not scanner_ignore.exists():
        return []
    patterns: list[str] = []
    for raw in scanner_ignore.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def normalise(path: str) -> str:
    """Normalise a scanner-reported path for matching.

    Scanners report paths in different shapes:
      - '/src/foo/bar.js'         (gitleaks, mounted under /src)
      - 'foo/bar.js'              (semgrep SARIF, relative)
      - 'apps/api/foo.js'         (trivy, relative)
      - '/Users/jd/.../foo.js'    (absolute on host)

    We strip the leading /src/ prefix (container mount) and any host prefix,
    then match against the .scannerignore patterns relative to project root.
    """
    p = path.replace("\\", "/").lstrip()
    # Strip container mount prefix
    for prefix in ("/src/", "/workspace/"):
        if p.startswith(prefix):
            return p[len(prefix):]
    return p


def matches_any(path: str, patterns: list[str]) -> bool:
    """Return True if path matches any pattern."""
    if not path:
        return False
    norm = normalise(path)
    for pat in patterns:
        # Treat trailing-slash patterns as directory matches
        if pat.endswith("/"):
            pat_no_slash = pat.rstrip("/")
            # Match if any path segment equals pat_no_slash
            segments = norm.split("/")
            if pat_no_slash in segments:
                return True
            # Also match glob (e.g. test/fixtures/)
            if fnmatch.fnmatch(norm, f"*{pat_no_slash}/*") or fnmatch.fnmatch(norm, f"*/{pat_no_slash}/*"):
                return True
        else:
            # Direct glob match
            if fnmatch.fnmatch(norm, pat):
                return True
            # Also match if pattern matches just the basename
            if fnmatch.fnmatch(norm.split("/")[-1], pat):
                return True
            # ** multi-segment
            if "**" in pat:
                # Convert ** to regex .*
                regex = re.escape(pat).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
                if re.fullmatch(regex, norm):
                    return True
    return False


# ===========================================================================
# Per-scanner filters
# ===========================================================================

def filter_semgrep(path: Path, patterns: list[str]) -> tuple[int, int]:
    """Filter Semgrep SARIF. Returns (before, after) finding counts."""
    data = json.loads(path.read_text(errors="replace"))
    total_before = 0
    total_after = 0
    for run in data.get("runs", []) or []:
        results = run.get("results", []) or []
        total_before += len(results)
        kept = []
        for r in results:
            locs = r.get("locations", []) or []
            paths = [
                (location.get("physicalLocation") or {}).get("artifactLocation", {}).get("uri", "")
                for location in locs
            ]
            if paths and all(matches_any(p, patterns) for p in paths):
                continue  # all locations ignored → drop result
            kept.append(r)
        run["results"] = kept
        total_after += len(kept)
    path.write_text(json.dumps(data, indent=2))
    return total_before, total_after


def filter_gitleaks(path: Path, patterns: list[str]) -> tuple[int, int]:
    """Filter Gitleaks JSON. Returns (before, after) finding counts."""
    data = json.loads(path.read_text(errors="replace"))
    if not isinstance(data, list):
        return 0, 0
    before = len(data)
    kept = [f for f in data if not matches_any(f.get("File", ""), patterns)]
    path.write_text(json.dumps(kept, indent=2))
    return before, len(kept)


def filter_trivy_config(path: Path, patterns: list[str]) -> tuple[int, int]:
    """Filter Trivy Config JSON (Misconfigurations only). Returns (before, after)."""
    data = json.loads(path.read_text(errors="replace"))
    before = 0
    after = 0
    for result in data.get("Results", []) or []:
        target = result.get("Target", "")
        # Drop the whole result if its target matches
        if matches_any(target, patterns):
            before += len(result.get("Misconfigurations", []) or [])
            result["Misconfigurations"] = []
            continue
        # Otherwise filter individual misconfigurations don't have per-file paths,
        # so we keep them all if the target itself is allowed.
        before += len(result.get("Misconfigurations", []) or [])
        after += len(result.get("Misconfigurations", []) or [])
    path.write_text(json.dumps(data, indent=2))
    return before, after


def filter_generic_trivy(path: Path, patterns: list[str]) -> tuple[int, int]:
    """Filter Trivy FS or image JSON: drop results whose Target matches patterns."""
    data = json.loads(path.read_text(errors="replace"))
    before = 0
    after = 0
    kept_results = []
    for result in data.get("Results", []) or []:
        target = result.get("Target", "")
        vulns = result.get("Vulnerabilities", []) or []
        secrets = result.get("Secrets", []) or []
        before += len(vulns) + len(secrets)
        if matches_any(target, patterns):
            # Whole result is ignored
            continue
        kept_results.append(result)
        after += len(vulns) + len(secrets)
    data["Results"] = kept_results
    path.write_text(json.dumps(data, indent=2))
    return before, after


def filter_grype(path: Path, patterns: list[str]) -> tuple[int, int]:
    """Filter Grype JSON: drop matches whose artifact path matches patterns."""
    data = json.loads(path.read_text(errors="replace"))
    before = len(data.get("matches", []) or [])
    kept = []
    for m in data.get("matches", []) or []:
        # artifact.locations is a list of {path, ...}
        locations = (m.get("artifact") or {}).get("locations", []) or []
        paths = [loc.get("path", "") if isinstance(loc, dict) else str(loc) for loc in locations]
        if paths and all(matches_any(p, patterns) for p in paths):
            continue
        kept.append(m)
    data["matches"] = kept
    path.write_text(json.dumps(data, indent=2))
    return before, len(kept)


def filter_syft(path: Path, patterns: list[str]) -> tuple[int, int]:
    """Filter Syft CycloneDX SBOM: drop components whose path matches patterns."""
    data = json.loads(path.read_text(errors="replace"))
    components = data.get("components", []) or []
    before = len(components)
    kept = []
    for c in components:
        # CycloneDX components may have purl and/or properties with path info
        c.get("purl", "") or ""
        # path may be in properties
        props = {p.get("name"): p.get("value", "") for p in c.get("properties", []) or []}
        file_path = props.get("syft:package:found_by") or props.get("syft:location:layer") or props.get("path", "")
        if file_path and matches_any(file_path, patterns):
            continue
        kept.append(c)
    data["components"] = kept
    path.write_text(json.dumps(data, indent=2))
    return before, len(kept)


FILTERS = {
    "semgrep":      filter_semgrep,
    "gitleaks":     filter_gitleaks,
    "trivy-config": filter_trivy_config,
    "trivy-fs":     filter_generic_trivy,
    "trivy-image":  filter_generic_trivy,
    "grype":        filter_grype,
    "grype-image":  filter_grype,
    "syft":         filter_syft,
    "syft-image":   filter_syft,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scanner-ignore", required=True)
    ap.add_argument("--scanner", required=True, choices=sorted(FILTERS.keys()))
    ap.add_argument("--output", required=True)
    ap.add_argument("--force", action="store_true",
                    help="Filter even for dependency scanners (default: refuse).")
    args = ap.parse_args()

    if args.scanner in DEPENDENCY_SCANNERS and not args.force:
        print(f"apply-scannerignore: skipping {args.scanner} (dependency scanner; use --force to override)",
              file=sys.stderr)
        return 0

    patterns = load_patterns(Path(args.scanner_ignore))
    if not patterns:
        print(f"apply-scannerignore: no patterns in {args.scanner_ignore}; nothing to do",
              file=sys.stderr)
        return 0

    output_path = Path(args.output)
    if not output_path.exists():
        print(f"apply-scannerignore: {output_path} does not exist; skipping",
              file=sys.stderr)
        return 0

    fn = FILTERS[args.scanner]
    before, after = fn(output_path, patterns)
    removed = before - after
    print(f"apply-scannerignore [{args.scanner}]: removed {removed} of {before} findings "
          f"({after} kept) using {len(patterns)} patterns", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
