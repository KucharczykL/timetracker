"""What a module's `ModelSchema`s are generated from.

Three modules argue "no API leak" from this scan: a hand
enumerated `Schema` publishes the fields it names, and a
`ModelSchema` publishes whatever the model grows. #1015 took
the last `ModelSchema` out of `games/api.py`, so the scan
finds nothing there now, and each caller states a probe of
its own so that a pass is the fact and not a broken scan.
"""

from collections.abc import Mapping

from ninja import ModelSchema


def models_covered(namespace: Mapping[str, object]) -> set[type]:
    """Every model a `ModelSchema` here generates fields from."""
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
