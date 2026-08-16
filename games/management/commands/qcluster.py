"""Start Django-Q only after the library structure is known to be complete."""

from django_q.management.commands.qcluster import Command as DjangoQCommand

from games.readiness import assert_library_structure


class Command(DjangoQCommand):
    def handle(self, *args, **options):
        assert_library_structure()
        return super().handle(*args, **options)
