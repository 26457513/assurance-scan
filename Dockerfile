FROM docker:29-cli

ARG COMPOSE_VERSION=v5.4.0

# Install compose as a Docker CLI plugin from the upstream release tarball.
# Avoids the Alpine `docker-cli-compose` apk, which pulls in an older apk-packaged
# docker-cli (compiled against vulnerable golang.org/x/crypto & x/net) that the
# base image's /usr/local/bin/docker shadows at runtime but that still pollutes
# the SBOM.
RUN apk upgrade --no-cache && apk add --no-cache \
    bash \
    coreutils \
    curl \
    findutils \
    gawk \
    git \
    grep \
    py3-jsonschema \
    py3-yaml \
    python3 \
    sed \
    tar \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-$(uname -m)" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

WORKDIR /opt/assurance-scan

LABEL org.opencontainers.image.source="https://github.com/jondowson/assurance-scan" \
      org.opencontainers.image.url="https://github.com/jondowson/assurance-scan" \
      org.opencontainers.image.documentation="https://github.com/jondowson/assurance-scan/blob/main/README.md" \
      org.opencontainers.image.title="assurance-scan" \
      org.opencontainers.image.description="Portable security scan and evidence bundle generator for application codebases, built around the OWASP Application Security Verification Standard."

COPY . /opt/assurance-scan

RUN rm -rf /opt/assurance-scan/reports /opt/assurance-scan/scripts/__pycache__ \
    && chmod +x /opt/assurance-scan/run-local.sh /opt/assurance-scan/scripts/*.sh /opt/assurance-scan/bin/assurance-scan \
    && ln -s /opt/assurance-scan/bin/assurance-scan /usr/local/bin/assurance-scan \
    && git config --system --add safe.directory '*'

ENTRYPOINT ["assurance-scan"]
CMD ["help"]
