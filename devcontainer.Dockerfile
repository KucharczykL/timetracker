FROM python:3.13-slim

# Set up environment
ENV PYTHONUNBUFFERED=1
WORKDIR /workspace

# Install Poetry
RUN apt-get update && apt-get install -y curl \
    && rm -rf /var/lib/apt/lists/*
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Copy pyproject.toml and poetry.lock for dependency installation
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root

# Copy the rest of the application code
COPY . .

# Set up Django development server
EXPOSE 8000
