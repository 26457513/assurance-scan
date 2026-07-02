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
    python3 \
    sed \
    tar

WORKDIR /opt/asvs-scanner
COPY . /opt/asvs-scanner

RUN rm -rf /opt/asvs-scanner/reports /opt/asvs-scanner/scripts/__pycache__ \
    && chmod +x /opt/asvs-scanner/run-local.sh /opt/asvs-scanner/scripts/*.sh /opt/asvs-scanner/bin/asvs-scanner \
    && ln -s /opt/asvs-scanner/bin/asvs-scanner /usr/local/bin/asvs-scanner

ENTRYPOINT ["asvs-scanner"]
CMD ["help"]
