# GitHub integration

GitHub supplies two independent identities:

- GitHub App user/installation access controls who and which repositories can
  participate and what people may see.
- GitHub Actions OIDC authenticates one workflow upload. It is never reused for
  browser or local CLI authentication.

There is no scan-result polling, manual retrieval, artifact download,
reconciliation job or source fetch. GitHub PATs are removed.

Read in order:

1. [GitHub App access](app-access.md)
2. [Webhook and repository sync](webhook-and-repository-sync.md)
3. [OIDC push ingestion](oidc-ingestion.md)
4. [Standard workflow](standard-workflow.md)
