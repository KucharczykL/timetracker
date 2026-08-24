"""The collaborators a command composes, named once.

`dispatch` folds a command through `idempotent_append` and `append`, each of
which hands a recorded event to the projector registry, checks its type
against the event-type registry, and retries under the retry policy. Threading
those three individually -- as `dispatch(..., registry=..., policy=...)` --
means every new collaborator grows the parameter list of every function on the
path, and a caller building the composed value one field at a time can drift
on what to call it. `EventWiring` names the whole bundle once, so a fourth
collaborator becomes a field here rather than another parameter everywhere.
"""

from dataclasses import dataclass

from games.events.projection import DEFAULT_REGISTRY, ProjectorRegistry
from games.events.retry import DEFAULT_RETRY_POLICY, RetryPolicy
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventTypeRegistry


@dataclass(frozen=True, slots=True)
class EventWiring:
    """Which projector registry, event-type registry, and retry policy a
    dispatch composes.

    The defaults are the production module-level singletons, not freshly
    constructed instances: a default-constructed `ProjectorRegistry()` would
    silently detach production from every registered projector family. A test
    substitutes one field by building its own `EventWiring` over its own
    registry -- exactly the substitutability the individual parameters gave.
    """

    projectors: ProjectorRegistry = DEFAULT_REGISTRY
    event_types: EventTypeRegistry = DEFAULT_EVENT_TYPES
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY


DEFAULT_WIRING = EventWiring()
