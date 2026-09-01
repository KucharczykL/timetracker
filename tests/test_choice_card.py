"""A whole row is one radio option."""

from common.components import ChoiceCard, ChoiceCardGroup

COLUMNS = "@2xl/edition:grid-cols-[5.5rem_minmax(0,1fr)_auto]"


def test_the_group_is_a_fieldset_naming_itself():
    rendered = str(ChoiceCardGroup(name="in_library", legend="Releases")["x"])

    assert "<fieldset" in rendered
    assert "<legend" in rendered
    assert "sr-only" in rendered
    assert "Releases" in rendered


def test_a_card_puts_its_mark_first():
    rendered = str(
        ChoiceCard(name="in_library", value="row-0", label="Show the Wii release")[
            "controls"
        ]
    )

    assert rendered.index("<input") < rendered.index("controls")


def test_a_card_names_its_mark_for_a_screen_reader():
    rendered = str(
        ChoiceCard(name="in_library", value="row-0", label="Show the Wii release")[""]
    )

    assert 'aria-label="Show the Wii release"' in rendered


def test_the_checked_hook_is_scoped_to_the_card_s_own_mark():
    """A hosted TemporalField holds checked radios of its own."""
    rendered = str(ChoiceCard(name="in_library", value="row-0", label="Wii")[""])

    assert "data-choice-card" in rendered
    assert "has-[[data-choice-card]:checked]:border-brand" in rendered
    assert "has-[:checked]:" not in rendered


def test_a_marked_card_carries_the_checked_attribute():
    marked = str(
        ChoiceCard(name="in_library", value="row-0", label="Wii", checked=True)[""]
    )
    plain = str(ChoiceCard(name="in_library", value="row-0", label="Wii")[""])

    assert 'checked="true"' in marked
    assert 'checked="true"' not in plain


def test_a_card_posts_its_name_and_value():
    rendered = str(
        ChoiceCard(name="in_library", value="edition-0-release-1", label="W")[""]
    )

    assert 'name="in_library"' in rendered
    assert 'value="edition-0-release-1"' in rendered
    assert 'type="radio"' in rendered


def test_the_group_and_its_card_declare_the_same_tracks():
    """Two grids that must line up cannot size themselves apart."""
    group = str(ChoiceCardGroup(name="m", legend="L", columns=COLUMNS)[""])
    card = str(ChoiceCard(name="m", value="v", label="L", columns=COLUMNS)[""])

    assert COLUMNS in group
    assert COLUMNS in card


def test_a_card_borders_itself_with_a_token_the_theme_states():
    """`border-default-soft` is not in the scale; it falls back to text."""
    rendered = str(ChoiceCard(name="m", value="v", label="L")[""])

    assert "border-default-soft" not in rendered
    assert "border-default" in rendered
