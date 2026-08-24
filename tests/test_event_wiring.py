"""The two registries `EventWiring` bundles, checked against each other.

Nothing at runtime cross-checks them, deliberately: registration order between
the projector registry and the event-type registry is not something to
constrain. The check belongs here instead.
"""

from games.events.wiring import DEFAULT_WIRING


def test_every_spec_a_default_projector_claims_is_a_registered_event_type():
    """A family claiming an unregistered spec registers fine and can never fire.

    `ProjectorRegistry.register` proves each `handles` key is an `EventSpec` --
    that the spec was *defined*, not that anything registered it. Append and
    replay both refuse an unknown event type before `apply`, so the family would
    silently never run: exactly the failure keying on specs exists to prevent.

    Both registries are empty today, so this costs nothing and catches the first
    real mismatch.
    """
    #: The registry exposes no public iteration.
    claimed = DEFAULT_WIRING.projectors._handlers

    unregistered = sorted(
        event_type
        for event_type in claimed
        if event_type not in DEFAULT_WIRING.event_types
    )

    assert unregistered == []
