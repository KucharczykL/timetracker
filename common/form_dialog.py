"""Whether a request comes from the form dialog."""

from typing import Final

from django.http import HttpRequest, HttpResponseRedirect

from common.components.form_dialog import CreatedOption

type HeaderName = str  # e.g. "X-Form-Dialog"

FORM_DIALOG_HEADER: Final[HeaderName] = "X-Form-Dialog"


def is_form_dialog(request: HttpRequest) -> bool:
    """The dialog asks for its answer kinds."""
    return request.headers.get(FORM_DIALOG_HEADER) == "1"


class CreatedRedirect(HttpResponseRedirect):
    """A redirect carrying the row it made."""

    def __init__(self, url: str, *, option: CreatedOption) -> None:
        super().__init__(url)
        self.option = option
