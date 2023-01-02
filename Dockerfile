FROM python:3.10-slim-bullseye
RUN apt update && apt install --no-install-recommends --yes git
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv pip $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN pip install --no-cache-dir poetry
RUN useradd --create-home --uid 1000 timetracker
RUN git clone https://git.kucharczyk.xyz/lukas/timetracker.git /home/timetracker/app
WORKDIR /home/timetracker/app
RUN poetry install
USER timetracker
EXPOSE 8000
CMD [ "python3", "src/web/manage.py", "runserver" ]