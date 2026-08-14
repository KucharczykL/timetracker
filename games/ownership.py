from django.shortcuts import get_object_or_404

from games.models import UserLibrary


def owned_or_404(queryset, library: UserLibrary, **lookup):
    """Resolve an object inside one explicit library or report it absent.

    The supplied queryset retains any select/prefetch policy chosen by the
    caller; its model-specific ``for_library`` method owns the relationship.
    """
    return get_object_or_404(queryset.for_library(library), **lookup)
