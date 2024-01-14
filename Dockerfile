FROM python:3.12.0-slim-bullseye

ENV VERSION_NUMBER=1.5.2 \
    PROD=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_ROOT_USER_ACTION=ignore \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR='/var/cache/pypoetry' \
    POETRY_HOME='/usr/local'

RUN apt-get update && apt-get upgrade -y \
  && apt-get install --no-install-recommends -y \
    bash \
    curl \
  && curl -sSL 'https://install.python-poetry.org' | python - \
  && poetry --version \
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && apt-get clean -y && rm -rf /var/lib/apt/lists/*

RUN useradd -m --uid 1000 timetracker \
    && mkdir -p '/var/www/django/static' \
    && chown timetracker:timetracker '/var/www/django/static'
WORKDIR /home/timetracker/app
COPY . /home/timetracker/app/
RUN chown -R timetracker:timetracker /home/timetracker/app
COPY entrypoint.sh /
RUN chmod +x /entrypoint.sh

RUN --mount=type=cache,target="$POETRY_CACHE_DIR" \
    echo "$PROD" \
    && poetry version \
    && poetry run pip install -U pip \
    && poetry install --only main --no-interaction --no-ansi --sync

USER timetracker

EXPOSE 8000
CMD [ "/entrypoint.sh" ]
