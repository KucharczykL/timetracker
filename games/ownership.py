from django.shortcuts import get_object_or_404

from games.models import UserLibrary


def owned_or_404(queryset, library: UserLibrary, **lookup):
    """Resolve an object from the queryset already scoped by the caller.

    The explicit library argument keeps the ownership boundary visible at every
    callsite; this helper deliberately applies only the requested lookup.
    """
    return get_object_or_404(queryset, **lookup)
