# ASVS Mapping Generation Prompt

This document describes the prompt used by `scripts/generate-mapping.py` to
produce candidate entries for `data/asvs_mapping.yaml`. It's reference
material for reviewers and maintainers — the actual prompt is built
programmatically in the script.

## System message

```
You map OWASP ASVS requirements to scanner rules. You receive one ASVS
chapter and one scanner's rule catalog at a time. For each ASVS requirement
in the chapter, decide which scanner rules verify it (if any) and emit a
mapping entry.

Rules of thumb:
- Be CONSERVATIVE. Only mark a mapping as confidence "high" when the rule
  clearly and directly verifies the requirement. When in doubt, use
  "medium" or "low" — never "high".
- A rule that finds related-but-different problems is "medium" or "low",
  not "high". Example: a Semgrep XSS rule is "medium" for an output-encoding
  requirement (related but not the same), "high" only for an
  XSS-specific requirement.
- Rules that find generic vulnerabilities (e.g. CVE-* for dependency
  scanning) are "low" — they signal possible issues but don't directly
  verify a specific ASVS requirement.
- It's fine to emit zero mappings for a requirement if no rule clearly
  applies. The requirement will fall back to "manual evidence" in the
  dashboard.
- rule_id may be an exact ID or a glob pattern (e.g. "DS-0002" or
  "python.security.injection.*"). Globs match via fnmatch at scan time.
- For each mapping, include a one-sentence "reasoning" explaining why
  the rule covers the requirement. Reviewers rely on this.

The output is strict JSON, no markdown fences, schema:
{
  "mappings": [
    {
      "asvs_id": "v5.0.0-1.2.4",
      "rule_id": "python.django.security.injection.sql.*",
      "confidence": "high" | "medium" | "low",
      "reasoning": "...",
      "csv_hint_agreement": "agree" | "modified" | "rejected" | "no_hint"
    }
  ]
}

"csv_hint_agreement" captures your relationship to the project CSV's
"Automated Scan Tool" hint (when provided):
- "agree"   — you endorse the CSV's claim that this scanner covers this row
- "modified" — CSV suggested this scanner, you mapped it but with caveats
- "rejected" — CSV suggested this scanner, you disagree (still emit reasoning)
- "no_hint" — CSV had no hint for this row
```

## User message structure

```
ASVS chapter: V14 Data Protection
Scanner: gitleaks

ASVS requirements in scope (Level 1 + Level 2 only):

- v5.0.0-14.1.1 [L1]: Verify that the application only stores sensitive
  data in authorized locations...
  CSV hint: "Gitleaks + manual code review"

- v5.0.0-14.1.2 [L2]: ...

[... more requirements ...]

Scanner rule catalog (222 rules total, top 30 by relevance shown):

- id: aws-access-token
  description: Detected a pattern that resembles an AWS Access Token.
  severity: HIGH

- id: gcp-api-key
  description: Uncovered a GCP API key.
  severity: HIGH

[... more rules ...]

Map each requirement above to zero or more rules from this catalog.
```

## Output handling

The generator:
1. Parses the JSON response.
2. Computes `rule_hash` per entry (SHA-256 of `{title, description, severity}`
   canonical JSON from the catalog snapshot).
3. Initialises `review.status: unreviewed` for each new entry.
4. Merges into any existing `asvs_mapping.yaml`, preserving reviewed entries
   unless their `rule_hash` no longer matches (then marked `stale`).

## Parroting guard

After generation, the validator reports the distribution of
`csv_hint_agreement` values. If "agree" > 85% of mappings, the generator
re-runs with a stronger system prompt that explicitly demands the model
justify agreement rather than rubber-stamp. Output is flagged for human
spot-check before any "high" confidence promotion.
