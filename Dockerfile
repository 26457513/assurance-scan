FROM docker:27-cli

RUN apk add --no-cache \
    bash \
    coreutils \
    curl \
    docker-cli-compose \
    findutils \
    gawk \
    git \
    grep \
    py3-yaml \
    python3 \
    sed \
    tar

WORKDIR /opt/asvs-scanner

LABEL org.opencontainers.image.source="https://github.com/jondowson/asvs-scanner" \
      org.opencontainers.image.url="https://github.com/jondowson/asvs-scanner" \
      org.opencontainers.image.documentation="https://github.com/jondowson/asvs-scanner/blob/main/README.md" \
      org.opencontainers.image.title="asvs-scanner" \
      org.opencontainers.image.description="Portable security scan and evidence bundle generator for application codebases, built around the OWASP Application Security Verification Standard."

COPY . /opt/asvs-scanner

RUN rm -rf /opt/asvs-scanner/reports /opt/asvs-scanner/scripts/__pycache__ \
    && chmod +x /opt/asvs-scanner/run-local.sh /opt/asvs-scanner/scripts/*.sh /opt/asvs-scanner/bin/asvs-scanner \
    && ln -s /opt/asvs-scanner/bin/asvs-scanner /usr/local/bin/asvs-scanner

ENTRYPOINT ["asvs-scanner"]
CMD ["help"]
