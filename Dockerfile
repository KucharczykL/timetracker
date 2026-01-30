FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /home/timetracker/app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.14-slim-bookworm

ENV PROD=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/timetracker/app/.venv/bin:$PATH"

RUN useradd -m --uid 1000 timetracker \
    && mkdir -p /var/www/django/static \
    && chown timetracker:timetracker /var/www/django/static
    
WORKDIR /home/timetracker/app

COPY --from=builder --chown=timetracker:timetracker /home/timetracker/app /home/timetracker/app

COPY --chown=timetracker:timetracker entrypoint.sh /
RUN chmod +x /entrypoint.sh

USER timetracker

ENV VERSION_NUMBER=1.6.1

EXPOSE 8000
CMD [ "/entrypoint.sh" ]
