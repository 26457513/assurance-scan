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
    py3-jsonschema \
    py3-yaml \
    python3 \
    sed \
    tar

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
