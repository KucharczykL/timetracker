"""How a request loads its user."""

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class LibraryModelBackend(ModelBackend):
    """Load the user and library together."""

    def get_user(self, user_id: Any) -> User | None:
        user_model = get_user_model()
        try:
            user = user_model.objects.select_related("library").get(pk=user_id)
        except user_model.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None
