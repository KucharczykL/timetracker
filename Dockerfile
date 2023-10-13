FROM node as css
WORKDIR /app
COPY . /app
RUN npm install && \
    npx tailwindcss -i ./common/input.css -o ./static/base.css --minify

FROM python:3.10.9-slim-bullseye

ENV VERSION_NUMBER 1.1.2
ENV PROD 1
ENV PYTHONUNBUFFERED=1

RUN useradd -m --uid 1000 timetracker
WORKDIR /home/timetracker/app
COPY . /home/timetracker/app/
RUN chown -R timetracker:timetracker /home/timetracker/app
COPY --from=css ./app/static/base.css /home/timetracker/app/static/base.css
COPY entrypoint.sh /
RUN chmod +x /entrypoint.sh

USER timetracker
ENV PATH="$PATH:/home/timetracker/.local/bin"
RUN pip install --no-cache-dir poetry
RUN poetry install

EXPOSE 8000
CMD [ "/entrypoint.sh" ]
