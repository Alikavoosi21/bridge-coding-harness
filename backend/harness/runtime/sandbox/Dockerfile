# The sandbox image the harness runs commands in.
#
# Reproducible build contract:
#
#   BASE_IMAGE must be a digest for a release build. The tag below is only the
#   developer default; CI and installers pass the digest explicitly:
#
#     docker build \
#       --build-arg BASE_IMAGE=python:3.12-slim-bookworm@sha256:<digest> \
#       -t bridge-coding-sandbox:0.2 harness/runtime/sandbox
#
#   The image contains no harness code, no secrets and no host paths. It is
#   only a userland: a shell plus the usual file tools and a Python runtime.
#   The runtime template (`harness/runtime/docker.py`) adds the confinement:
#   non-root, read-only rootfs, no network, dropped capabilities, limits.
#
# Keep this file small. Everything installed here is available to every
# command an agent may run, so extra packages widen the attack surface.

ARG BASE_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:24-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205
FROM ${NODE_IMAGE} AS node-runtime
FROM ${BASE_IMAGE}

# The two preset families must execute in the actual sandbox, not only in UI fixtures.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    npm_config_cache=/tmp/npm-cache

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        libstdc++6 \
        git \
        curl \
        less \
        ripgrep \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# UID/GID 1000 matches the `--user 1000:1000` in the run template.
RUN groupadd --gid 1000 sandbox \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash sandbox

WORKDIR /workspace
USER 1000:1000

# The command is supplied by the runtime (`sh -lc <command>`). This default
# exits immediately, so a mistaken run without a command cannot linger.
CMD ["sh", "-lc", "exit 0"]
