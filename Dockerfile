# Stage 1: Build stage to leverage uv
FROM python:3.12-slim AS builder

# Copy uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

#UV_COMPILE_BYTECODE environment variable to ensure that all commands within the Dockerfile compile bytecode
ENV UV_COMPILE_BYTE=1
#UV_LINK_MODE silences warnings about not being able to link files since the cache and sync target are on separate file systems.
ENV UV_LINK_MODE=copy

# Set working directory
WORKDIR /app

# Copy dependency files first for Docker caching
#COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Stage 2: Final lightweight runtime image
#FROM python:3.12-slim

#WORKDIR /app

# Copy the virtual environment from the builder stage
#COPY --from=builder /app/.venv /app/.venv

# Copy your application code
COPY . /app

# Ensure the app uses the virtual environment's python and dependencies
#ENV PATH="/code/.venv/bin:$PATH"

EXPOSE 8000

# Command to run FastAPI using the synced environment
CMD ["uv","run","fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]
