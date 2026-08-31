"""Developer-only page for spot-checking the #965 temporal field.

Nothing hosts a temporal field until #969, so there is nowhere to look
at one. This page carries two: a plain field and a stored range. It is
routed only when DEBUG was true at import time, and it goes away with
the branch that added it.
"""

from django import forms
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse

from common.components import (
    ContentContainer,
    ControlButton,
    CsrfInput,
    Div,
    Form,
    FormFields,
    PageHeading,
)
from common.components.primitives import P
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from games.forms import TemporalFormField
from timetracker.temporal import TemporalValue


class TemporalPreviewForm(forms.Form):
    """One collapsed field and one that opens showing its range."""

    def __init__(self, *args, presentation, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["released"] = TemporalFormField(
            presentation=presentation, label="Release date"
        )
        self.fields["supported"] = TemporalFormField(
            presentation=presentation, label="Support window"
        )


@login_required
def temporal_field_preview(request: HttpRequest) -> HttpResponse:
    presentation = date_time_presentation_for_request(request)
    initial = {"supported": TemporalValue.parse("1984/1986~")}
    form = TemporalPreviewForm(
        request.POST or None, presentation=presentation, initial=initial
    )
    stored: list[str] = []
    if request.method == "POST" and form.is_valid():
        stored = [
            f"{name}: {value!r} renders as {value}" if value else f"{name}: nothing"
            for name, value in form.cleaned_data.items()
        ]

    return render_page(
        request,
        ContentContainer(class_="flex flex-col gap-6")[
            PageHeading("Temporal field preview"),
            Form(method="post", class_="flex flex-col gap-4 @container")[
                CsrfInput(request),
                FormFields(form),
                ControlButton(type="submit", color="blue")["Save"],
            ],
            Div(class_="flex flex-col gap-1")[*[P()[line] for line in stored]],
        ],
        title="Temporal field preview",
    )
