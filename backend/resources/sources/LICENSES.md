# Source Data Licenses

Each snapshot in this directory is generated from a third-party source. The original sources retain their licenses; this file records what was fetched, when, and under what terms.

## OWASP ASVS 5.0.0

- **Source:** https://github.com/OWASP/ASVS/tree/v5.0.0
- **License:** CC BY-SA 4.0 — https://creativecommons.org/licenses/by-sa/4.0/
- **Snapshot file:** `data/rulesets/asvs/5.0.0.json`
- **Attribution:** "OWASP Application Security Verification Standard, © OWASP Foundation, used under CC BY-SA 4.0."

## Semgrep rules-owasp-asvs

- **Source:** https://github.com/semgrep-old/rules-owasp-asvs
- **License:** MPL 2.0 — https://www.mozilla.org/en-US/MPL/2.0/
- **Snapshot file:** `semgrep_rules.json`
- **Attribution:** "Semgrep OWASP ASVS rules, used under MPL 2.0."

## Semgrep community rules

- **Source:** https://github.com/semgrep/semgrep-rules
- **License:** LGPL 2.1 — https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- **Snapshot file:** `semgrep_rules.json` (merged with the ASVS-rules snapshot above)
- **Attribution:** "Semgrep Community Rules, used under LGPL 2.1."

## Trivy misconfig checks (trivy-checks / defsec)

- **Source:** https://github.com/aquasecurity/trivy-checks (engine: https://github.com/aquasecurity/defsec)
- **License:** Apache 2.0 — https://www.apache.org/licenses/LICENSE-2.0
- **Snapshot files:** `trivy_vuln_rules.json` (limited), `trivy_config_rules.json`, `trivy_secret_rules.json` (limited)
- **Attribution:** "Trivy misconfiguration checks (trivy-checks), used under Apache 2.0."

## Gitleaks rules

- **Source:** https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml
- **License:** MIT — https://opensource.org/license/mit/
- **Snapshot file:** `gitleaks_rules.json`
- **Attribution:** "Gitleaks default rules, used under the MIT License."

## OWASP ZAP passive scan rules

- **Source:** https://www.zaproxy.org/docs/alerts/
- **License:** Apache 2.0 — https://www.apache.org/licenses/LICENSE-2.0
- **Snapshot file:** `zap_rules.json`
- **Attribution:** "OWASP ZAP passive scan rules documentation, used under Apache 2.0."

## security-headers

- **Source:** in-repo at `scripts/security-headers.py`
- **License:** Same as the assurance-scan project.
- **Snapshot file:** `security_headers_rules.json`
- **Attribution:** "assurance-scan's bundled security-headers check script."

## testssl.sh

- **Source:** https://github.com/testssl/testssl.sh
- **License:** GPL v2 — https://www.gnu.org/licenses/old-licenses/gpl-2.0.html
- **Snapshot file:** `testssl_rules.json` (category-level only; no rule IDs)
- **Attribution:** "testssl.sh check categories, used under GPL v2. Note: only check category names are captured; no code is redistributed."

---

## Snapshot Maintenance

Ruleset snapshots are stored as canonical `ruleset.schema.json` artifacts under
`data/rulesets/<ruleset>/<version>.json`. Scanner-to-compliance mappings are
stored separately as reviewed `scanner-compliance-mapping-pack.schema.json`
artifacts under `data/scanner-mappings/<ruleset>/<version>/`.

Legacy YAML scanner mappings and `data/frameworks/*/requirements.json` snapshots
are no longer supported active artifacts.
