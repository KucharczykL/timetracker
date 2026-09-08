"""What a module's `ModelSchema`s are generated from.

Three modules argue "no API leak" from this scan. No
`ModelSchema` is left in `games/api.py`, so each caller
states a probe of its own: a pass is then the fact, and
not a broken scan.
"""

from collections.abc import Mapping

from ninja import ModelSchema


def models_covered(namespace: Mapping[str, object]) -> set[type]:
    """Every model a `ModelSchema` here names."""
    covered: set[type] = set()
    for member in namespace.values():
        if (
            not isinstance(member, type)
            or not issubclass(member, ModelSchema)
            or member is ModelSchema
        ):
            continue
        model = getattr(getattr(member, "Meta", None), "model", None)
        if model is not None:
            covered.add(model)
    return covered
