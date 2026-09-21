"""How a request loads the user it acts for."""

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class LibraryModelBackend(ModelBackend):
    """Load the user with its library in one statement.

    Nearly every view scopes itself on `request.user.library`,
    and `library` is a reverse one-to-one, so the join costs
    nothing beyond the row it fetches. Without it the library
    is a second statement on every authenticated request, and
    a reader that asks the library a further question -- the
    navbar asks its calendar what day it is -- pays for that
    statement rather than for its own question.
    """

    def get_user(self, user_id: Any) -> User | None:
        user_model = get_user_model()
        try:
            user = user_model.objects.select_related("library").get(pk=user_id)
        except user_model.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None
