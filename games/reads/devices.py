"""Devices a library holds."""

from django.db.models import QuerySet

from games.models import Device, UserLibrary


def held_devices(library: UserLibrary) -> QuerySet[Device]:
    """Live devices whose access has not ended."""
    return Device.objects.for_library(library).filter(
        access_end_recorded_at__isnull=True
    )
