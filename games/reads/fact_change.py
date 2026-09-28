"""One fact, before a batch and as it stated."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FactChange[T]:
    """One fact, before a batch and as it stated."""

    before: T
    stated: T
