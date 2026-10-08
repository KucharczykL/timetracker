"""Fast password hashing for tests."""

import pytest


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    """A test proves no hash's strength."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
