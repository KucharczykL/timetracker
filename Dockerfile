FROM node as css
WORKDIR /app
COPY . /app
RUN npm install && \
    npx tailwindcss -i ./src/input.css -o ./src/web/tracker/static/base.css --minify

FROM python:3.10.9-slim-bullseye

ENV VERSION_NUMBER 0.2.5
ENV PROD 1
ENV PYTHONUNBUFFERED=1

RUN apt update && \
    apt install -y \
    bash \
    vim \
    curl && \
    apt install -y debian-keyring debian-archive-keyring apt-transport-https && \
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg && \
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list && \
    apt update && \
    apt install caddy && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m --uid 1000 timetracker
WORKDIR /home/timetracker/app
COPY . /home/timetracker/app/
RUN chown -R timetracker:timetracker /home/timetracker/app
COPY --from=css /app/src/web/tracker/static/base.css /home/timetracker/app/src/web/tracker/static/base.css
COPY entrypoint.sh /
RUN chmod +x /entrypoint.sh

USER timetracker
ENV PATH="$PATH:/home/timetracker/.local/bin"
RUN pip install --no-cache-dir poetry
RUN poetry install --without dev

EXPOSE 8000
ENTRYPOINT [ "/entrypoint.sh" ]