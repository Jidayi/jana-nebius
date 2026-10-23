# Local reproduction of the CI offline job (ARC-17) on Linux, with the pinned toolchains.
#   docker build -f scripts/ci/offline.Dockerfile -t jana-offline .
#   scripts/ci/offline-local.sh            # runs the full suite under the offline harness
FROM node:24.21.0-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends strace iproute2 sudo curl ca-certificates git bubblewrap \
    build-essential pkg-config libwebkit2gtk-4.1-dev libgtk-3-dev libsoup-3.0-dev libxdo-dev libssl-dev librsvg2-dev \
 && rm -rf /var/lib/apt/lists/*
# The webkit and gtk development packages build the Tauri shell (D18) on Linux.
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /usr/local/bin/
RUN useradd -m -s /bin/bash runner && echo "runner ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/runner
USER runner
ENV PATH=/home/runner/.local/bin:/home/runner/.cargo/bin:$PATH COREPACK_ENABLE_DOWNLOAD_PROMPT=0 TURBO_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain 1.97.1 \
 && rustup component add clippy rustfmt
RUN mkdir -p /home/runner/.local/bin && corepack enable --install-directory /home/runner/.local/bin
WORKDIR /work
