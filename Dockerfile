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

# Codegen the TypeScript prop contracts (needs Django); tsc compiles them in
# the assets stage below.
RUN uv run python manage.py gen_element_types


# Front-end assets: Tailwind CSS + the TypeScript custom elements. Built here so
# the compiled output ships in the image (dist/ is build-only, not committed).
FROM node:22-bookworm-slim AS assets

WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install --frozen-lockfile
COPY . .
COPY --from=builder /home/timetracker/app/ts/generated ./ts/generated
RUN pnpm tailwindcss -i ./common/input.css -o ./games/static/base.css \
    && pnpm exec tsc


FROM python:3.14-slim-bookworm

ENV PROD=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/timetracker/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libcap2-bin \
    supervisor \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m --uid 1000 timetracker \
    && mkdir -p /var/log/supervisor /etc/supervisor/conf.d /home/timetracker/data \
    && chown timetracker:timetracker /var/log/supervisor /home/timetracker/data

ARG CADDY_VERSION=2.9.1
RUN curl -sL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_amd64.tar.gz" \
    -o /tmp/caddy.tar.gz && \
    tar -xzf /tmp/caddy.tar.gz -C /tmp && \
    mv /tmp/caddy /usr/local/bin/caddy && \
    rm /tmp/caddy.tar.gz && \
    chmod +x /usr/local/bin/caddy

WORKDIR /home/timetracker/app

COPY --from=builder --chown=timetracker:timetracker /home/timetracker/app /home/timetracker/app

# Built front-end assets from the Node stage (Tailwind CSS + compiled TS).
COPY --from=assets --chown=timetracker:timetracker /app/games/static/base.css /home/timetracker/app/games/static/base.css
COPY --from=assets --chown=timetracker:timetracker /app/games/static/js/dist /home/timetracker/app/games/static/js/dist

COPY --chown=timetracker:timetracker Caddyfile /etc/caddy/Caddyfile
COPY --chown=timetracker:timetracker supervisor.conf /etc/supervisor/conf.d/supervisor.conf
COPY --chown=timetracker:timetracker entrypoint.sh /
RUN chmod +x /entrypoint.sh

ENV VERSION_NUMBER=1.7.0

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
