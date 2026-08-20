// Mirror of server/worker/sarif.py SCANNER_DESCRIPTIONS (frontend-safe copy).
export const SCANNER_DESCRIPTIONS: Record<string, string> = {
  semgrep: 'static code analysis',
  gitleaks: 'hardcoded secrets',
  'trivy-fs': 'dependency CVEs (fs)',
  'trivy-config': 'Dockerfile/IaC misconfig',
  'trivy-image': 'image CVEs',
  syft: 'SBOM inventory',
  grype: 'dependency CVEs',
  'osv-scanner': 'dependency CVEs (OSV)',
  tribal: 'repo-defined checks',
  'project-tests': 'project test suite',
};
