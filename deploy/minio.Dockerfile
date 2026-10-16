# syntax=docker/dockerfile:1.7
# MinIO server and client built from source at pinned releases.
#
# MinIO no longer publishes community container images, so the stack builds its own from
# the upstream repositories (AGPLv3) at fixed release tags. The result runs as an
# unprivileged user and contains only the two binaries.

FROM golang:1.24-bookworm AS build
ARG MINIO_RELEASE=RELEASE.2025-10-15T17-29-55Z
ARG MC_RELEASE=RELEASE.2025-08-13T08-35-41Z
ENV CGO_ENABLED=0 GOFLAGS=-trimpath
RUN git clone --depth 1 --branch "$MINIO_RELEASE" https://github.com/minio/minio /src/minio \
 && cd /src/minio && go build -ldflags "-s -w" -o /out/minio .
RUN git clone --depth 1 --branch "$MC_RELEASE" https://github.com/minio/mc /src/mc \
 && cd /src/mc && go build -ldflags "-s -w" -o /out/mc .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10002 minio \
 && useradd --system --uid 10002 --gid minio --home-dir /data --shell /usr/sbin/nologin minio \
 && mkdir -p /data && chown minio:minio /data
COPY --from=build /out/minio /out/mc /usr/local/bin/
USER minio
ENV HOME=/data
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
