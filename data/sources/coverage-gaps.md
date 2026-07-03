# Coverage Gaps

Scanner rules in source snapshots that are NOT referenced by any ASVS
mapping entry. These are candidates for new mappings — see the plan §1.5.
Total: **426 of 426 catalog rules unreferenced**.


Generated: `data/sources/coverage-gaps.md`

## gitleaks (222 of 222 rules unreferenced)

- `1password-secret-key`
  Uncovered a possible 1Password secret key, potentially compromising access to secrets in vaults.
- `1password-service-account-token`
  Uncovered a possible 1Password service account token, potentially compromising access to secrets in vaults.
- `adafruit-api-key`
  Identified a potential Adafruit API Key, which could lead to unauthorized access to Adafruit services and sensitive data exposure.
- `adobe-client-id`
  Detected a pattern that resembles an Adobe OAuth Web Client ID, posing a risk of compromised Adobe integrations and data breaches.
- `adobe-client-secret`
  Discovered a potential Adobe Client Secret, which, if exposed, could allow unauthorized Adobe service access and data manipulation.
- `age-secret-key`
  Discovered a potential Age encryption tool secret key, risking data decryption and unauthorized access to sensitive information.
- `airtable-api-key`
  Uncovered a possible Airtable API Key, potentially compromising database access and leading to data leakage or alteration.
- `airtable-personnal-access-token`
  Uncovered a possible Airtable Personal AccessToken, potentially compromising database access and leading to data leakage or alteration.
- `algolia-api-key`
  Identified an Algolia API Key, which could result in unauthorized search operations and data exposure on Algolia-managed platforms.
- `alibaba-access-key-id`
  Detected an Alibaba Cloud AccessKey ID, posing a risk of unauthorized cloud resource access and potential data compromise.
- `alibaba-secret-key`
  Discovered a potential Alibaba Cloud Secret Key, potentially allowing unauthorized operations and data access within Alibaba Cloud.
- `anthropic-admin-api-key`
  Detected an Anthropic Admin API Key, risking unauthorized access to administrative functions and sensitive AI model configurations.
- `anthropic-api-key`
  Identified an Anthropic API Key, which may compromise AI assistant integrations and expose sensitive data to unauthorized access.
- `artifactory-api-key`
  Detected an Artifactory api key, posing a risk unauthorized access to the central repository.
- `artifactory-reference-token`
  Detected an Artifactory reference token, posing a risk of impersonation and unauthorized access to the central repository.
- `asana-client-id`
  Discovered a potential Asana Client ID, risking unauthorized access to Asana projects and sensitive task information.
- `asana-client-secret`
  Identified an Asana Client Secret, which could lead to compromised project management integrity and unauthorized access.
- `atlassian-api-token`
  Detected an Atlassian API token, posing a threat to project management and collaboration tool security and data confidentiality.
- `authress-service-client-access-key`
  Uncovered a possible Authress Service Client Access Key, which may compromise access control services and sensitive data.
- `aws-access-token`
  Identified a pattern that may indicate AWS credentials, risking unauthorized cloud resource access and data breaches on AWS platforms.
- `aws-amazon-bedrock-api-key-long-lived`
  Identified a pattern that may indicate long-lived Amazon Bedrock API keys, risking unauthorized Amazon Bedrock usage
- `aws-amazon-bedrock-api-key-short-lived`
  Identified a pattern that may indicate short-lived Amazon Bedrock API keys, risking unauthorized Amazon Bedrock usage
- `azure-ad-client-secret`
  Azure AD Client Secret
- `beamer-api-token`
  Detected a Beamer API token, potentially compromising content management and exposing sensitive notifications and updates.
- `bitbucket-client-id`
  Discovered a potential Bitbucket Client ID, risking unauthorized repository access and potential codebase exposure.
- `bitbucket-client-secret`
  Discovered a potential Bitbucket Client Secret, posing a risk of compromised code repositories and unauthorized access.
- `bittrex-access-key`
  Identified a Bittrex Access Key, which could lead to unauthorized access to cryptocurrency trading accounts and financial loss.
- `bittrex-secret-key`
  Detected a Bittrex Secret Key, potentially compromising cryptocurrency transactions and financial security.
- `cisco-meraki-api-key`
  Cisco Meraki is a cloud-managed IT solution that provides networking, security, and device management through an easy-to-use interface.
- `clickhouse-cloud-api-secret-key`
  Identified a pattern that may indicate clickhouse cloud API secret key, risking unauthorized clickhouse cloud api access and data breaches on ClickHouse Cloud platforms.
- `clojars-api-token`
  Uncovered a possible Clojars API token, risking unauthorized access to Clojure libraries and potential code manipulation.
- `cloudflare-api-key`
  Detected a Cloudflare API Key, potentially compromising cloud application deployments and operational security.
- `cloudflare-global-api-key`
  Detected a Cloudflare Global API Key, potentially compromising cloud application deployments and operational security.
- `cloudflare-origin-ca-key`
  Detected a Cloudflare Origin CA Key, potentially compromising cloud application deployments and operational security.
- `codecov-access-token`
  Found a pattern resembling a Codecov Access Token, posing a risk of unauthorized access to code coverage reports and sensitive data.
- `cohere-api-token`
  Identified a Cohere Token, posing a risk of unauthorized access to AI services and data manipulation.
- `coinbase-access-token`
  Detected a Coinbase Access Token, posing a risk of unauthorized access to cryptocurrency accounts and financial transactions.
- `confluent-access-token`
  Identified a Confluent Access Token, which could compromise access to streaming data platforms and sensitive data flow.
- `confluent-secret-key`
  Found a Confluent Secret Key, potentially risking unauthorized operations and data access within Confluent services.
- `contentful-delivery-api-token`
  Discovered a Contentful delivery API token, posing a risk to content management systems and data integrity.
- `curl-auth-header`
  Discovered a potential authorization token provided in a curl command header, which could compromise the curl accessed resource.
- `curl-auth-user`
  Discovered a potential basic authorization token provided in a curl command, which could compromise the curl accessed resource.
- `databricks-api-token`
  Uncovered a Databricks API token, which may compromise big data analytics platforms and sensitive data processing.
- `datadog-access-token`
  Detected a Datadog Access Token, potentially risking monitoring and analytics data exposure and manipulation.
- `defined-networking-api-token`
  Identified a Defined Networking API token, which could lead to unauthorized network operations and data breaches.
- `digitalocean-access-token`
  Found a DigitalOcean OAuth Access Token, risking unauthorized cloud resource access and data compromise.
- `digitalocean-pat`
  Discovered a DigitalOcean Personal Access Token, posing a threat to cloud infrastructure security and data privacy.
- `digitalocean-refresh-token`
  Uncovered a DigitalOcean OAuth Refresh Token, which could allow prolonged unauthorized access and resource manipulation.
- `discord-api-token`
  Detected a Discord API key, potentially compromising communication channels and user data privacy on Discord.
- `discord-client-id`
  Identified a Discord client ID, which may lead to unauthorized integrations and data exposure in Discord applications.
- _...and 172 more_

## security_headers (6 of 6 rules unreferenced)

- `content-security-policy`
  Set a Content-Security-Policy to mitigate XSS and injection.
- `permissions-policy`
  Set a Permissions-Policy to lock down browser features.
- `referrer-policy`
  Set a Referrer-Policy to limit referrer leakage.
- `strict-transport-security`
  Enable HSTS to enforce HTTPS.
- `x-content-type-options`
  Set 'nosniff' to prevent MIME-type sniffing.
- `x-frame-options`
  Set DENY or SAMEORIGIN to prevent clickjacking.

## trivy_config (197 of 197 rules unreferenced)

- `DS-0001` — "':latest' tag used"
  "When using a 'FROM' statement you should use a specific tag to avoid uncontrolled behavior when the image is updated."
- `DS-0002` — "Image user should not be 'root'"
  "Running containers with 'root' user can lead to a container escape situation. It is a best practice to run containers as non-root users, which can be done by adding a 'USER' statement to the Dockerfi
- `DS-0004` — "Port 22 exposed"
  "Exposing port 22 might allow users to SSH into the container."
- `DS-0005` — ADD instead of COPY
  You should use COPY instead of ADD unless you want to extract a tar file. Note that an ADD command will extract a tar file, which adds the risk of Zip-based vulnerabilities. Accordingly, it is advised
- `DS-0006` — "COPY '--from' referring to the current image"
  "COPY '--from' should not mention the current FROM alias, since it is impossible to copy from itself."
- `DS-0007` — "Multiple ENTRYPOINT instructions listed"
  "There can only be one ENTRYPOINT instruction in a Dockerfile. Only the last ENTRYPOINT instruction in the Dockerfile will have an effect."
- `DS-0008` — "Exposed port out of range"
  "UNIX ports outside the range 0-65535 are exposed."
- `DS-0009` — "WORKDIR path not absolute"
  "For clarity and reliability, you should always use absolute paths for your WORKDIR."
- `DS-0010` — "RUN using 'sudo'"
  "Avoid using 'RUN' with 'sudo' commands, as it can lead to unpredictable behavior."
- `DS-0011` — "COPY with more than two arguments not ending with slash"
  "When a COPY command has more than two arguments, the last one should end with a slash."
- `DS-0012` — "Duplicate aliases defined in different FROMs"
  "Different FROMs can't have the same alias defined."
- `DS-0013` — "'RUN cd ...' to change directory"
  "Use WORKDIR instead of proliferating instructions like 'RUN cd … && do-something', which are hard to read, troubleshoot, and maintain."
- `DS-0014` — "RUN using 'wget' and 'curl'"
  "Avoid using both 'wget' and 'curl' since these tools have the same effect."
- `DS-0015` — "'yum clean all' missing"
  "You should use 'yum clean all' after using a 'yum install' command to clean package cached data and reduce image size."
- `DS-0016` — "Multiple CMD instructions listed"
  "There can only be one CMD instruction in a Dockerfile. If you list more than one CMD then only the last CMD will take effect."
- `DS-0017` — "'RUN <package-manager> update' instruction alone"
  "The instruction 'RUN <package-manager> update' should always be followed by '<package-manager> install' in the same RUN statement."
- `DS-0019` — "'dnf clean all' missing"
  "Cached package data should be cleaned after installation to reduce image size."
- `DS-0020` — "'zypper clean' missing"
  "The layer and image size should be reduced by deleting unneeded caches after running zypper."
- `DS-0021` — "'apt-get' missing '-y' to avoid manual input"
  "'apt-get' calls should use the flag '-y' to avoid manual user input."
- `DS-0022` — "Deprecated MAINTAINER used"
  "MAINTAINER has been deprecated since Docker 1.13.0."
- `DS-0023` — "Multiple HEALTHCHECK defined"
  "Providing more than one HEALTHCHECK instruction per stage is confusing and error-prone."
- `DS-0024` — "'apt-get dist-upgrade' used"
  "'apt-get dist-upgrade' upgrades a major version so it doesn't make more sense in Dockerfile."
- `DS-0025` — "'apk add' is missing '--no-cache'"
  "You should use 'apk add' with '--no-cache' to clean package cached data and reduce image size."
- `DS-0026` — "No HEALTHCHECK defined"
  "You should add HEALTHCHECK instruction in your docker container images to perform the health check on running containers."
- `DS-0027` — "'microdnf clean all' missing"
  "Cached package data should be cleaned after installation to reduce image size."
- `DS-0029` — "'apt-get' missing '--no-install-recommends'"
  "'apt-get' install should use '--no-install-recommends' to minimize image size."
- `DS-0030` — "WORKDIR should not be mounted on system dirs"
  "WORKDIR should not be mounted on system directories to avoid container breakouts"
- `DS-0031` — Secrets passed via `build-args` or envs or copied secret files
  Passing secrets via `build-args` or envs or copying secret files can leak them out
- `KCV-0001` — "Ensure that the --anonymous-auth argument is set to false"
  "Disable anonymous requests to the API server."
- `KCV-0002` — "Ensure that the --token-auth-file parameter is not set"
  "Do not use token based authentication."
- `KCV-0003` — "Ensure that the --DenyServiceExternalIPs is not set"
  "This admission controller rejects all net-new usage of the Service field externalIPs."
- `KCV-0004` — "Ensure that the --kubelet-https argument is set to true"
  "Use https for kubelet connections."
- `KCV-0005` — "Ensure that the --kubelet-client-certificate and --kubelet-client-key arguments are set as appropriate"
  "Enable certificate based kubelet authentication."
- `KCV-0006` — "Ensure that the --kubelet-certificate-authority argument is set as appropriate"
  "Verify kubelet's certificate before establishing connection."
- `KCV-0007` — "Ensure that the --authorization-mode argument is not set to AlwaysAllow"
  "Do not always authorize all requests."
- `KCV-0008` — "Ensure that the --authorization-mode argument includes Node"
  "Restrict kubelet nodes to reading only objects associated with them."
- `KCV-0009` — "Ensure that the --authorization-mode argument includes RBAC"
  "Turn on Role Based Access Control."
- `KCV-0010` — "Ensure that the admission control plugin EventRateLimit is set"
  "Limit the rate at which the API server accepts requests."
- `KCV-0011` — "Ensure that the admission control plugin AlwaysAdmit is not set"
  "Do not allow all requests."
- `KCV-0012` — "Ensure that the admission control plugin AlwaysPullImages is set"
  "Always pull images."
- `KCV-0013` — "Ensure that the admission control plugin SecurityContextDeny is set if PodSecurityPolicy is not used"
  "The SecurityContextDeny admission controller can be used to deny pods which make use of some SecurityContext fields which could allow for privilege escalation in the cluster. This should be used wher
- `KCV-0014` — "Ensure that the admission control plugin ServiceAccount is set"
  "Automate service accounts management."
- `KCV-0015` — "Ensure that the admission control plugin NamespaceLifecycle is set"
  "Reject creating objects in a namespace that is undergoing termination."
- `KCV-0016` — "Ensure that the admission control plugin NodeRestriction is set"
  "Limit the Node and Pod objects that a kubelet could modify."
- `KCV-0017` — "Ensure that the --secure-port argument is not set to 0"
  "Do not disable the secure port."
- `KCV-0018` — "Ensure that the --profiling argument is set to false"
  "Disable profiling, if not needed."
- `KCV-0019` — "Ensure that the --audit-log-path argument is set"
  "Enable auditing on the Kubernetes API Server and set the desired audit log path."
- `KCV-0020` — "Ensure that the --audit-log-maxage argument is set to 30 or as appropriate"
  "Retain the logs for at least 30 days or as appropriate."
- `KCV-0021` — "Ensure that the --audit-log-maxbackup argument is set to 10 or as appropriate"
  "Retain 10 or an appropriate number of old log files."
- `KCV-0022` — "Ensure that the --audit-log-maxsize argument is set to 100 or as appropriate"
  "Rotate log files on reaching 100 MB or as appropriate."
- _...and 147 more_

## trivy_vuln (1 of 1 rules unreferenced)

- `CVE-*` — Any CVE discovered by Trivy dependency scanning
  Trivy vulnerabilities are CVE IDs sourced from NVD and GitHub Advisories at scan time. There is no static rule catalog — map ASVS requirements to this entry with the glob 'CVE-*'.

