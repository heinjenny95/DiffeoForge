# syntax=docker/dockerfile:1.7

# Python 3.8.20 on Debian Bookworm, pinned to the official multi-platform
# manifest. The runtime lock intentionally supports linux/amd64 only because
# the official PyTorch 1.6 CPU wheel is architecture-specific.
FROM python:3.8.20@sha256:d411270700143fa2683cc8264d9fa5d3279fd3b6afff62ae81ea2f9d070e390c

# Deformetrica imports its Qt GUI package even for headless CLI execution.
# These signed Debian Bookworm packages provide the required libGL.so.1 ABI.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        libgl1=1.6.0-1 \
        libglvnd0=1.6.0-1 \
        libglx0=1.6.0-1 \
    && test -e /usr/lib/x86_64-linux-gnu/libGL.so.1 \
    && rm -rf /var/lib/apt/lists/*

LABEL org.opencontainers.image.title="DiffeoForge Deformetrica reference backend" \
      org.opencontainers.image.description="Frozen CPU execution environment for Deformetrica 4.3.0" \
      org.opencontainers.image.source="https://github.com/heinjenny95/DiffeoForge" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="4.3.0-cpu.1"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    USE_CUDA=0 \
    CUDA_VISIBLE_DEVICES=-1

COPY container/requirements-bootstrap.lock /tmp/requirements-bootstrap.lock
RUN python -m pip install --no-cache-dir --require-hashes \
        --requirement /tmp/requirements-bootstrap.lock

COPY container/requirements-deformetrica-4.3.0-cpu.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes \
        --requirement /tmp/requirements.lock \
    && python -m pip check \
    && python -c "import importlib.metadata as m, torch; assert m.version('deformetrica') == '4.3.0'; assert torch.__version__ == '1.6.0+cpu'; assert not torch.cuda.is_available()" \
    && test "$(uname -m)" = "x86_64" \
    && g++ --version \
    && cmake --version \
    && rm -f /tmp/requirements-bootstrap.lock /tmp/requirements.lock

# PyKeOps 1.4.1 compiles formula-specific CPU kernels on first use. The
# launcher supplies an executable tmpfs and a read-only root filesystem.
ENV HOME=/tmp \
    PYKEOPS_VERBOSE=0

WORKDIR /work
ENTRYPOINT ["deformetrica"]
CMD ["--help"]
