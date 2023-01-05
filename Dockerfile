FROM node as css
COPY . /
RUN apt install -y npm && \
    npm install && \
    npx tailwindcss -i ./src/input.css -o ./src/web/tracker/static/base.css --minify

FROM python:3.10-slim-bullseye

ENV VERSION_NUMBER 0.1.0-34-g8efce77

RUN useradd --create-home --uid 1000 timetracker && \
    pip install --no-cache-dir poetry && \
    poetry install --without dev

WORKDIR /home/timetracker/app
COPY . /home/timetracker/app/
RUN chown -R timetracker:timetracker /home/timetracker/app

COPY entrypoint.sh /
RUN chmod +x /entrypoint.sh
USER timetracker
EXPOSE 8000
ENTRYPOINT [ "/entrypoint.sh" ]