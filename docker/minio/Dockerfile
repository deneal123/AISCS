# Same MinIO release as the inherited platform, built from its exact source
# commit because its historical public container registries are unavailable.
FROM golang:1.24.6-bookworm AS builder
ARG MINIO_COMMIT=07c3a429bfed433e49018cb0f78a52145d4bedeb
ARG MINIO_SOURCE_SHA256=8819e3e7817e46b7b3798f8f200ead208562e571563c2e040352378031abe9f2
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOMAXPROCS=4
WORKDIR /src
RUN curl --fail --show-error --location --retry 2 --retry-all-errors --max-time 180 \
      "https://codeload.github.com/minio/minio/tar.gz/${MINIO_COMMIT}" -o /tmp/minio.tar.gz \
    && echo "${MINIO_SOURCE_SHA256}  /tmp/minio.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/minio.tar.gz --strip-components=1 -C /src \
    && rm /tmp/minio.tar.gz
# Exact fields from upstream buildscripts/gen-ldflags.go, without manufacturing
# a Git checkout for an archive build. Source integrity is checked above.
RUN --mount=type=cache,id=aspa-minio-modules,target=/go/pkg/mod \
    --mount=type=cache,id=aspa-minio-build,target=/root/.cache/go-build \
    go mod download && go mod verify \
    && go build -p 4 -buildvcs=false -trimpath -ldflags="-s -w \
      -X github.com/minio/minio/cmd.Version=2025-09-07T16:13:09Z \
      -X github.com/minio/minio/cmd.CopyrightYear=2025 \
      -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-09-07T16-13-09Z \
      -X github.com/minio/minio/cmd.CommitID=${MINIO_COMMIT} \
      -X github.com/minio/minio/cmd.ShortCommitID=07c3a429bfed \
      -X github.com/minio/minio/cmd.GOPATH=/go \
      -X github.com/minio/minio/cmd.GOROOT=/usr/local/go" -o /out/minio .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl bash \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /out/minio /usr/local/bin/minio
COPY --from=builder /src/LICENSE /usr/share/doc/minio/LICENSE
LABEL org.opencontainers.image.source="https://github.com/minio/minio" \
    org.opencontainers.image.revision="07c3a429bfed433e49018cb0f78a52145d4bedeb" \
    org.opencontainers.image.version="RELEASE.2025-09-07T16-13-09Z" \
    org.opencontainers.image.licenses="AGPL-3.0-or-later"
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
