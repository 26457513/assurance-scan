# Shared finding source context

Actions and local execution extract context from the same immutable snapshot
the scanners read. The server never substitutes source fetched later from
GitHub, and the GitHub App has no repository-content permission.

## Contract

Before normalization, the producer assigns each source record a deterministic
`finding_key`: UUIDv5 over schema version, scanner identity, rule identity,
normalized path, original range, message fingerprint and stable occurrence
ordinal. Findings and contexts carry the same key through filtering,
deduplication and persistence; orphan or duplicate keys reject the bundle.
Available entries contain repository-relative path, inclusive source window,
original highlight range, numbered lines, provider, source-content hash,
`redaction_version` and `redaction_changed`. Unavailable entries contain no
source text and one stable reason.

An available context contains at most eleven total lines:

- single-line finding: up to five before, affected line and five after;
- multi-line finding: affected range consumes the fixed allowance, with
  remaining lines allocated around it up to five per side;
- range longer than eleven: anchor at its first affected line, clip to eleven,
  retain original range metadata and set `highlight_truncated=true`.

Overlapping windows are deduplicated and safely referenced by multiple
findings. File-only findings never receive a guessed line.

## Safety limits

- 500 unique windows/request;
- 11 lines/window, 1 KiB UTF-8/line and 8 KiB UTF-8/window; the window cap wins
  and truncation occurs on a Unicode boundary with an explicit marker;
- 2 MiB decoded context text/request.

Binary, oversized, invalid-path and untrusted-range inputs produce explicit
unavailable reasons. Exceeding context limits never drops the finding.

Client extraction removes incidental scanner snippets and applies a versioned,
deterministic redaction policy before outbox/network writes. The server requires
a supported version, validates that every context hash matches the run source
manifest, and re-redacts before persistence. Tests cover every supported secret
detector, absolute-path removal, boundary truncation and representative full-file
exfiltration attempts; the contract does not claim detection of every possible
unknown secret format.

The UI uses one finding-scoped endpoint for both origins, labels provider and
redaction, and explains stable unavailable reasons. Dirty local runs use only
their uploaded snapshot context. Historical findings return `not_uploaded`;
there is no GitHub fallback.
