"""The collaborators a command composes, named once."""

from dataclasses import dataclass

from games.events.projection import DEFAULT_REGISTRY, ProjectorRegistry
from games.events.retry import DEFAULT_RETRY_POLICY, RetryPolicy
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventTypeRegistry


@dataclass(frozen=True, slots=True)
class EventWiring:
    """The registries and policy a dispatch uses."""

    projectors: ProjectorRegistry = DEFAULT_REGISTRY
    event_types: EventTypeRegistry = DEFAULT_EVENT_TYPES
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY


DEFAULT_WIRING = EventWiring()
