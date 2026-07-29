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

# A checkout without LFS substitutes pointer files for the fonts, icons and the
# sample fixture. Nothing downstream errors on that — the image just serves
# 130-byte text files as woff2, and every webfont dies in the browser's font
# sanitizer. Fail the build instead.
RUN pointers="$(grep -rlI 'https://git-lfs.github.com/spec/v1' . || true)"; \
    if [ -n "$pointers" ]; then \
        echo "Git LFS pointer files in the build context (checkout needs lfs: true):" >&2; \
        echo "$pointers" >&2; \
        exit 1; \
    fi

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Codegen the TypeScript prop contracts (needs Django); tsc compiles them in
# the assets stage below.
RUN uv run python manage.py gen_element_types


# Front-end assets: Tailwind CSS + the TypeScript custom elements. Built here so
# the compiled output ships in the image (dist/ is build-only, not committed).
FROM node:26-bookworm-slim AS assets

WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# Node 26 no longer bundles Corepack, so install the version pinned in
# package.json's "packageManager" field explicitly.
RUN npm install --global pnpm@10.33.0 \
    && pnpm install --frozen-lockfile --ignore-scripts
COPY . .
COPY --from=builder /home/timetracker/app/ts/generated ./ts/generated
RUN pnpm tailwindcss -i ./common/input.css -o ./games/static/base.css \
    && pnpm exec tsc


FROM python:3.14-slim-bookworm

ENV PROD=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/timetracker/app/.venv/bin:$PATH" \
    # Read by supervisor.conf, which cannot be parsed with it unset. Deployments
    # that schedule nothing (staging) set false and save the cluster's ~260mb.
    RUN_QCLUSTER=true \
    # Django's in-code default is BASE_DIR; pin the image default so the
    # database lands inside the expected volume even without -e DATA_DIR.
    DATA_DIR=/home/timetracker/app/data

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    supervisor \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m --uid 1000 timetracker \
    && mkdir -p /etc/supervisor/conf.d /home/timetracker/app/data \
    && chown -R timetracker:timetracker /home/timetracker/app

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

# Collect static here rather than in the entrypoint: the output is a pure
# function of the image's own files, and hashing them takes a Django startup
# plus a dozen post-process passes that every container start would otherwise
# repeat while the first request waits. SECRET_KEY is only needed because the
# runtime stage sets PROD=1; it is scoped to this layer and never in the image.
RUN SECRET_KEY=collectstatic-build python manage.py collectstatic --no-input \
    && chown -R timetracker:timetracker /home/timetracker/app/static

COPY --chown=timetracker:timetracker Caddyfile /etc/caddy/Caddyfile
COPY --chown=timetracker:timetracker supervisor.conf /etc/supervisor/conf.d/supervisor.conf
COPY --chown=timetracker:timetracker entrypoint.sh /
RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
    && chmod +x /entrypoint.sh

# Displayed in the footer. CI bakes main-<sha> for main builds, <slug>-<sha>
# for staging, vX.Y.Z for release rebuilds; "dev" is the no-CI fallback.
ARG VERSION_NUMBER=dev
ENV VERSION_NUMBER=$VERSION_NUMBER

USER timetracker

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -sf http://127.0.0.1:8000/health || exit 1

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
