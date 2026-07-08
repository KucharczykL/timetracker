"""Create (or repair) the dev superuser and print login instructions.

Idempotent: every run converges the user to a usable superuser, which fixes the
common "user exists but the password was never set" case. Uses the
DEV_LOGIN_PREFILL credentials when set, else admin/admin.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from games.dev_login import prefill_credentials


class Command(BaseCommand):
    help = "Create/repair the dev superuser and print login instructions."

    def handle(self, *args, **options) -> None:
        username, password = prefill_credentials() or ("admin", "admin")
        user_model = get_user_model()
        user, _created = user_model.objects.get_or_create(username=username)
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(
            self.style.SUCCESS(
                f"Superuser '{username}' ready.\n"
                f"Run `make dev`, open /login/ — the credentials are prefilled "
                f"when DEV_LOGIN_PREFILL is set; click Login."
            )
        )
