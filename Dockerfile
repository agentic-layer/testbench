FROM python:3.13-slim

# Install runtime and build dependencies (git is needed for Gitpython, which is a dependency of Ragas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install UV package manager
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using UV
RUN uv sync

# Copy scripts to root dir
COPY scripts/* ./

# Create directories for data and results
RUN mkdir -p data/datasets data/experiments results

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Make scripts executable
RUN chmod +x *.py

# Set 'uv run python3' entrypoint so we can run scripts directly
ENTRYPOINT ["uv", "run", "python3"]
