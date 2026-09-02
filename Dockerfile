# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Stage 1: build the SvelteKit frontend
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci --ignore-scripts

COPY frontend/ ./
RUN npm run check && npm run build


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
COPY backend/requirements/server.txt /tmp/requirements-server.txt

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip "setuptools>=78.1.1" \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements-server.txt


# ---------------------------------------------------------------------------
# Stage 3: runtime image (clean — no compilers)
# ---------------------------------------------------------------------------
FROM docker:29-cli

ARG COMPOSE_VERSION=v5.4.0
ARG VERSION=dev
ARG REVISION=unknown

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

WORKDIR /opt/assurance-scan/backend

LABEL org.opencontainers.image.source="https://github.com/26457513/assurance-scan" \
      org.opencontainers.image.url="https://github.com/26457513/assurance-scan" \
      org.opencontainers.image.documentation="https://github.com/26457513/assurance-scan/blob/main/docs/module-architecture.md" \
      org.opencontainers.image.title="assurance-scan" \
      org.opencontainers.image.description="Assurance scanning service exposing scans via REST, MCP, and a SvelteKit UI." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

# Built frontend
COPY --from=frontend /app/build /opt/assurance-scan/backend/app/static

# Backend source layout. Keep the image paths aligned with the repository so
# scripts and runtime resource resolution behave the same locally and in CI.
COPY backend/app/ /opt/assurance-scan/backend/app/
COPY backend/bin/ /opt/assurance-scan/backend/bin/
COPY backend/scripts/ /opt/assurance-scan/backend/scripts/
COPY backend/resources/ /opt/assurance-scan/backend/resources/
COPY backend/alembic.ini /opt/assurance-scan/backend/
COPY docker-compose.security.yml /opt/assurance-scan/backend/docker-compose.security.yml

# Entrypoint
RUN chmod +x /opt/assurance-scan/backend/app/entrypoint.sh \
    && ln -s /opt/assurance-scan/backend/app/entrypoint.sh /usr/local/bin/assurance-scan

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
