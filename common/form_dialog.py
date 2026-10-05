"""Whether a request comes from the form dialog."""

from typing import Final

from django.http import HttpRequest, HttpResponse

from common.components.form_dialog import CreatedOption

type HeaderName = str  # e.g. "X-Form-Dialog"

FORM_DIALOG_HEADER: Final[HeaderName] = "X-Form-Dialog"


def is_form_dialog(request: HttpRequest) -> bool:
    """The dialog asks for its answer kinds."""
    return request.headers.get(FORM_DIALOG_HEADER) == "1"


#: The attribute a tagged redirect carries.
_CREATED_ATTRIBUTE: Final = "form_dialog_created"


def created_row[Response: HttpResponse](
    response: Response, option: CreatedOption
) -> Response:
    """Tags a redirect with the row it made."""
    setattr(response, _CREATED_ATTRIBUTE, option)
    return response


def created_option(response: HttpResponse) -> CreatedOption | None:
    """The row a redirect was tagged with."""
    return getattr(response, _CREATED_ATTRIBUTE, None)
