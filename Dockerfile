FROM python:3.10-slim-bullseye
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv pip $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN pip install --no-cache-dir poetry
RUN useradd --create-home --uid 1000 timetracker
WORKDIR /home/timetracker/app
COPY . /home/timetracker/app/
RUN chown -R timetracker:timetracker /home/timetracker/app
RUN poetry install --without dev
COPY entrypoint.sh /
RUN chmod +x /entrypoint.sh
USER timetracker
EXPOSE 8000
ENV VERSION_NUMBER $(git describe --tags --abbrev=0)
ENTRYPOINT [ "/entrypoint.sh" ]