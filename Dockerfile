FROM python:3.13-slim

# Install runtime and build dependencies (git is needed for Gitpython, which is a dependency of Ragas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install UV package manager
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv

# Copy package source and dependency files (README and LICENSE required for hatchling build)
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY testbench/ ./testbench/

# Install dependencies and the testbench package itself
RUN uv sync

# Create directories for data and results
RUN mkdir -p data/datasets data/experiments results

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run modules under uv-managed Python; templates pass `-m testbench.<module>` and any args.
ENTRYPOINT ["uv", "run", "python3"]
