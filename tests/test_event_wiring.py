"""The two registries EventWiring bundles, cross-checked."""

from games.events.wiring import DEFAULT_WIRING


def test_every_spec_a_default_projector_claims_is_a_registered_event_type():
    """An unregistered claim can never fire."""
    #: The registry exposes no public iteration, and adding one for a test
    #: would be the larger change.
    claimed = DEFAULT_WIRING.projectors._handlers

    unregistered = sorted(
        event_type
        for event_type in claimed
        if event_type not in DEFAULT_WIRING.event_types
    )

    assert unregistered == []
