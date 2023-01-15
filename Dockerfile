FROM node as css
WORKDIR /app
COPY . /app
RUN npm install && \
    npx tailwindcss -i ./src/input.css -o ./src/web/tracker/static/base.css --minify

FROM python:3.10.9-alpine

ENV VERSION_NUMBER 0.2.1-2-g734e6de
ENV PROD 1

RUN apk add \
    bash \
    vim \
    curl \
    caddy
RUN adduser -D -u 1000 timetracker
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