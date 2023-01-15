import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import date2num
import base64
from io import BytesIO
from tracker.models import Session
from django.db.models import Sum, IntegerField, F
from django.db.models.functions import TruncDay
import logging
from datetime import datetime
from django.db.models import QuerySet


def key_value_to_value_value(data):
    return {data["date"]: data["hours"]}


def playtime_over_time_chart(queryset: QuerySet = Session.objects):
    microsecond_in_second = 1000000
    result = (
        queryset.annotate(date=TruncDay("timestamp_start"))
        .values("date")
        .annotate(
            hours=Sum(
                F("duration_calculated") + F("duration_manual"),
                output_field=IntegerField(),
            )
        )
        .values("date", "hours")
    )
    keys = []
    values = []
    running_total = int(0)
    for item in result:
        date_value = datetime.strftime(item["date"], "%d-%m-%Y")
        keys.append(date_value)
        running_total += int(item["hours"] / (3600 * microsecond_in_second))
        values.append(running_total)
    data = [keys, values]
    return get_chart(data, title="Playtime over time", xlabel="Date", ylabel="Hours")


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
    plt.style.use("dark_background")
    plt.switch_backend("SVG")
    fig = plt.figure(figsize=(10, 4))
    plt.plot(data[0], data[1])
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.tight_layout()
    chart = get_graph()
    return chart
