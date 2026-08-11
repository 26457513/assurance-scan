# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Stage 1: build the SvelteKit frontend
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app

COPY frontend/package*.json ./
# Use npm install — package-lock.json in this repo isn't kept perfectly in sync
# with package.json (npm ci fails). npm install is more forgiving and produces
# a working build.
RUN npm install

COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2: build Python wheels (gcc / musl-dev / python3-dev only here)
# ---------------------------------------------------------------------------
FROM docker:29-cli AS pybuilder

RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-virtualenv \
    gcc \
    musl-dev \
    python3-dev

WORKDIR /build
COPY requirements-server.txt /tmp/

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip "setuptools>=78.1.1" \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements-server.txt


# ---------------------------------------------------------------------------
# Stage 3: runtime image (clean — no compilers)
# ---------------------------------------------------------------------------
FROM docker:29-cli

ARG COMPOSE_VERSION=v5.4.0

# Compose as a CLI plugin from the upstream release. Avoids the Alpine
# docker-cli-compose apk which drags in an older apk-packaged docker-cli
# compiled against vulnerable Go libraries.
RUN apk upgrade --no-cache && apk add --no-cache \
    bash \
    coreutils \
    curl \
    findutils \
    gawk \
    git \
    grep \
    sed \
    tar \
    python3 \
    py3-jsonschema \
    py3-yaml \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-$(uname -m)" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Copy the pre-built venv from the builder stage (no compiler needed here).
COPY --from=pybuilder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /opt/assurance-scan

LABEL org.opencontainers.image.source="https://github.com/jondowson/assurance-scan" \
      org.opencontainers.image.url="https://github.com/jondowson/assurance-scan" \
      org.opencontainers.image.documentation="https://github.com/jondowson/assurance-scan/blob/main/docs/mcp-stack-plan.md" \
      org.opencontainers.image.title="assurance-scan" \
      org.opencontainers.image.description="Single-user, locally-running assurance service exposing scans via REST + MCP and a SvelteKit UI."

# Built frontend
COPY --from=frontend /app/build /opt/assurance-scan/server/static

# Application code
COPY server/ /opt/assurance-scan/server/
COPY alembic.ini /opt/assurance-scan/

# JSON Schemas used at runtime by the catalogue loader
COPY data/schemas/ /opt/assurance-scan/data/schemas/

# Workflow prompt definitions served via MCP
COPY data/workflows/ /opt/assurance-scan/data/workflows/

# Compliance packs (framework row data — agent reads these to draft mappings)
COPY data/compliance-packs/ /opt/assurance-scan/data/compliance-packs/

# Entrypoint
RUN chmod +x /opt/assurance-scan/server/entrypoint.sh \
    && ln -s /opt/assurance-scan/server/entrypoint.sh /usr/local/bin/assurance-scan

# /data must be bind-mounted from the host for persistence.
RUN mkdir -p /data
VOLUME ["/data"]

# Bind uvicorn to all interfaces inside the container. Host-side
# `-p 127.0.0.1:8000:8000` enforces the localhost-only security model.
ENV ASSURANCE_SCAN_HOST=0.0.0.0 \
    ASSURANCE_SCAN_PORT=8000

# Project bind-mount ($PWD) is required at runtime via -v "$PWD:$PWD" -w "$PWD".
# Root required for docker socket access (FR-SCAN-EXEC); see waiver on FR-CONTAINER-HYGIENE.
ENTRYPOINT ["assurance-scan"] # nosemgrep: dockerfile.security.missing-user-entrypoint.missing-user-entrypoint
CMD ["serve"] # nosemgrep: dockerfile.security.missing-user.missing-user

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8000/health || exit 1
