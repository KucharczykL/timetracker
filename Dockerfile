FROM node as css
WORKDIR /app
COPY . /app
RUN npm install && \
    npx tailwindcss -i ./src/input.css -o ./src/web/tracker/static/base.css --minify

FROM python:3.10-slim-bullseye

ENV VERSION_NUMBER 0.1.0-39-gf7ec079
ENV PROD 1

RUN useradd --create-home --uid 1000 timetracker
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