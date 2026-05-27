# syntax=docker/dockerfile:1.7
#
# PREQ-A-2: Dockerfile with FROM pinned by digest, apt + pip pinned by version + hash.
#
# Base image digest is the multi-arch manifest list digest for
# python:3.12-slim-bookworm (linux/amd64 + linux/arm64 + ...).
# Regenerate with:
#     docker buildx imagetools inspect python:3.12-slim-bookworm
# When the digest moves (Debian point release), update this line AND
# scoring-spec.yaml::worker_image atomically in the same commit.
FROM python:3.12-slim-bookworm@sha256:93ab4b7fa528b25124c97bcc755415e60eb671a86b4dbe0328df2fe2d1c1193d

# --- PREQ-X-1: install git>=2.50.1 from upstream tarball -----------------------
# Debian backports does not currently carry git 2.50.x (highest available across
# bookworm/trixie is 2.47.3 as of 2026-05). Build from upstream sha256-pinned
# source to satisfy PREQ-X-1.
#
# Regenerate digests with:
#   curl -fsSL https://mirrors.edge.kernel.org/pub/software/scm/git/sha256sums.asc \
#     | grep "git-${GIT_VERSION}.tar.xz"
ARG GIT_VERSION=2.50.1
ARG GIT_TARBALL_SHA256=7e3e6c36decbd8f1eedd14d42db6674be03671c2204864befa2a41756c5c8fc4
ARG CA_CERTIFICATES_VERSION=20230311+deb12u1
ARG CURL_VERSION=7.88.1-10+deb12u14

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      ca-certificates="${CA_CERTIFICATES_VERSION}" \
      curl="${CURL_VERSION}"; \
    apt-get install -y --no-install-recommends \
      build-essential \
      gettext \
      libcurl4-openssl-dev \
      libexpat1-dev \
      libssl-dev \
      libz-dev \
      pkg-config \
      xz-utils; \
    cd /tmp; \
    curl -fsSL -o git.tar.xz "https://mirrors.edge.kernel.org/pub/software/scm/git/git-${GIT_VERSION}.tar.xz"; \
    echo "${GIT_TARBALL_SHA256}  git.tar.xz" | sha256sum -c -; \
    tar -xJf git.tar.xz; \
    cd "git-${GIT_VERSION}"; \
    make -j"$(nproc)" prefix=/usr/local NO_TCLTK=1 NO_GETTEXT=YesPlease NO_PERL=1 NO_PYTHON=1 all >/dev/null; \
    make prefix=/usr/local NO_TCLTK=1 NO_GETTEXT=YesPlease NO_PERL=1 NO_PYTHON=1 install >/dev/null; \
    cd /tmp && rm -rf "git-${GIT_VERSION}" git.tar.xz; \
    apt-get purge -y --auto-remove \
      build-essential \
      gettext \
      libcurl4-openssl-dev \
      libexpat1-dev \
      libssl-dev \
      libz-dev \
      pkg-config \
      xz-utils; \
    rm -rf /var/lib/apt/lists/*; \
    git --version

# --- PREQ-A-2: pip deps via hash-checked lockfile ------------------------------
# Note: requirements.lock.txt now includes `lizard==1.17.31` (a pure-Python
# console-script analyzer). Its sha256 is verified by pip via --require-hashes.
WORKDIR /opt/cce
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock.txt

# --- scc (sloc/complexity/cocomo counter) --------------------------------------
# Installed from the upstream GitHub release tarball, sha256-verified at build.
# Regenerate digest with:
#   curl -fsSL https://github.com/boyter/scc/releases/download/v${SCC_VERSION}/scc_Linux_x86_64.tar.gz | sha256sum
# When SCC_VERSION moves, update BOTH the version arg AND the digest arg.
ARG SCC_VERSION=3.5.0
ARG SCC_SHA256=6cb156fc5667b1a97b654ff5e4c9c2c937870adbe00d7380b64a4a4c5bca2e0b
ARG SCC_URL=https://github.com/boyter/scc/releases/download/v${SCC_VERSION}/scc_Linux_x86_64.tar.gz
RUN set -eux; \
    if [ "${SCC_SHA256}" = "0000000000000000000000000000000000000000000000000000000000000000" ]; then \
      echo "SCC_SHA256 is unset; pass --build-arg SCC_SHA256=<real-hex>" >&2; exit 1; \
    fi; \
    cd /tmp; \
    curl -fsSL -o scc.tar.gz "${SCC_URL}"; \
    echo "${SCC_SHA256}  scc.tar.gz" | sha256sum -c -; \
    tar -xzf scc.tar.gz scc; \
    install -m 0755 scc /usr/local/bin/scc; \
    rm -f scc scc.tar.gz; \
    scc --version

# --- Project source ------------------------------------------------------------
COPY pyproject.toml README.md ./
COPY src ./src
COPY scoring-spec.yaml ./
RUN pip install --no-cache-dir --no-deps .

# --- Health check (depends on pip-installed cce CLI) ---------------------------
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD cce --help > /dev/null || exit 1

# --- Non-root user; scored repos are mounted read-only at /work ----------------
RUN useradd --uid 1001 --create-home --shell /usr/sbin/nologin cce

# --- Production analyzer registry binding -------------------------------------
# The shim calls register_production_backends() before delegating to cce.cli's
# entrypoint(), so AnalyzerRegistry.assert_digests has lizard/scc bound with
# binary_resolver closures and is no longer a no-op in the production image.
# COPY + chmod run as root (before the USER cce switch) so the file is mode
# 0755 and executable by the non-root runtime user.
COPY ops/docker/cce-entrypoint.py /usr/local/bin/cce-entrypoint
RUN chmod +x /usr/local/bin/cce-entrypoint

USER cce
WORKDIR /work

ENTRYPOINT ["cce-entrypoint"]
CMD ["--help"]
