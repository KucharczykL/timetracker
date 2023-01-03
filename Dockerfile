FROM python:3.10-slim-bullseye
RUN apt update \
    && apt install --no-install-recommends --yes \
    git \
    make \
    && rm -rf /var/lib/apt/lists/*
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv pip $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN pip install --no-cache-dir poetry
RUN useradd --create-home --uid 1000 timetracker
RUN git clone https://git.kucharczyk.xyz/lukas/timetracker.git /home/timetracker/app
WORKDIR /home/timetracker/app
RUN chown -R timetracker /home/timetracker/app
RUN poetry install
RUN make loadplatforms
EXPOSE 8000
VOLUME [ "/home/timetracker/app/src/web/db.sqlite3" ]
USER timetracker
CMD [ "python3", "src/web/manage.py", "runserver", "0.0.0.0:8000" ]