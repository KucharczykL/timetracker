"""Whether a request comes from the form dialog."""

from typing import Final

from django.http import HttpRequest

type HeaderName = str  # e.g. "X-Form-Dialog"

FORM_DIALOG_HEADER: Final[HeaderName] = "X-Form-Dialog"


def is_form_dialog(request: HttpRequest) -> bool:
    """The dialog asks for its answer kinds."""
    return request.headers.get(FORM_DIALOG_HEADER) == "1"
