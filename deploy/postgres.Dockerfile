# syntax=docker/dockerfile:1.7
# PostgreSQL 16 (the official Alpine image the stack already runs) with pgvector, built from
# source at a pinned release for semantic visual search.
#
# Staying on postgres:16-alpine matters for existing deployments: the data volume keeps the
# same C library (musl) and therefore the same collation behaviour; switching to a Debian-based
# image would require reindexing text indexes. pgvector is compiled without LLVM JIT bitcode
# (with_llvm=no) and without CPU-specific flags (OPTFLAGS=""), so the image runs on any x86-64
# or arm64 host; build dependencies are removed in the same layer.

FROM postgres:16-alpine
ARG PGVECTOR_VERSION=0.8.7
RUN apk add --no-cache --virtual .pgvector-build git build-base \
 && git clone --depth 1 --branch "v${PGVECTOR_VERSION}" https://github.com/pgvector/pgvector.git /tmp/pgvector \
 && make -C /tmp/pgvector OPTFLAGS="" with_llvm=no \
 && make -C /tmp/pgvector OPTFLAGS="" with_llvm=no install \
 && rm -rf /tmp/pgvector \
 && apk del .pgvector-build
