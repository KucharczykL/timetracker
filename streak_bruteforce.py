import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "timetracker.settings")
django.setup()

from common.time import streak_bruteforce
from games.models import Session

all = Session.objects.filter(timestamp_start__gt="1970-01-01")

data = []

for session in all:
    current = session.timestamp_start
    data.append(current.date())

start = time.time_ns()
start_cpu = time.process_time_ns()
print(streak_bruteforce(data))
end = time.time_ns()
end_cpu = time.process_time_ns()
print(
    f"Processed {all.count()} items in {((end - start)/ 1_000_000_000):.10f} seconds and {((end_cpu - start_cpu)/ 1_000_000_000):.10f} seconds of process time."
)
