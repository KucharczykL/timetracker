import datetime
from zoneinfo import ZoneInfo

print(
    datetime.datetime.isoformat(
        datetime.datetime.now(ZoneInfo("Europe/Prague")),
        timespec="minutes",
        sep=" ",
    )
)
