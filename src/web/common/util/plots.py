import base64
from datetime import datetime
from io import BytesIO

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
from django.db.models import F, IntegerField, QuerySet, Sum
from django.db.models.functions import TruncDay
from tracker.models import Session


def key_value_to_value_value(data):
    return {data["date"]: data["hours"]}


def playtime_over_time_chart(queryset: QuerySet = Session.objects):
    microsecond_in_second = 1000000
    result = (
        queryset.exclude(timestamp_end__exact=None)
        .annotate(date=TruncDay("timestamp_start"))
        .values("date")
        .annotate(
            hours=Sum(
                F("duration_calculated"),
                output_field=IntegerField(),
            )
        )
        .values("date", "hours")
    )
    keys = []
    values = []
    running_total = int(0)
    for item in result:
        # date_value = datetime.strftime(item["date"], "%d-%m-%Y")
        date_value = item["date"]
        keys.append(date_value)
        running_total += int(item["hours"] / (3600 * microsecond_in_second))
        values.append(running_total)
    data = [keys, values]
    return get_chart(
        data,
        title="Playtime over time (manual excluded)",
        xlabel="Date",
        ylabel="Hours",
    )


def get_graph():
    buffer = BytesIO()
    plt.savefig(buffer, format="svg", transparent=True)
    buffer.seek(0)
    image_png = buffer.getvalue()
    graph = base64.b64encode(image_png)
    graph = graph.decode("utf-8")
    buffer.close()
    return graph


def get_chart(data, title="", xlabel="", ylabel=""):
    x = data[0]
    y = data[1]
    plt.style.use("dark_background")
    plt.switch_backend("SVG")
    fig, ax = plt.subplots()
    fig.set_size_inches(10, 4)
    ax.plot(x, y)
    first = x[0]
    last = x[-1]
    difference = last - first
    if difference.days <= 14:
        ax.xaxis.set_major_locator(mdates.DayLocator())
    elif difference.days < 60 or len(x) < 60:
        ax.xaxis.set_major_locator(mdates.WeekdayLocator())
        ax.xaxis.set_minor_locator(mdates.DayLocator())
    elif difference.days < 720:
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_minor_locator(mdates.WeekdayLocator())
    else:
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_minor_locator(mdates.MonthLocator())

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    for label in ax.get_xticklabels(which="major"):
        label.set(rotation=30, horizontalalignment="right")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    fig.tight_layout()
    chart = get_graph()
    return chart
