"""A form states the facts its opener names."""

import re
import uuid

import pytest
from django import forms
from django.http import QueryDict
from django.urls import reverse

from common.components import FormFieldGroup, FormFields
from common.components.primitives import FIELD_BOX_SHAPE_CLASS, field_box_class
from common.opener_facts import Fixed, OpenerFactsMixin, Refused, refusal_sentence
from common.returns import action_url
from games.models import Game

KIND_CHOICES = [("main", "Main game"), ("dlc", "DLC")]


class GameFactsForm(OpenerFactsMixin, forms.Form):
    opener_fields = ("game", "kind")

    game = forms.ModelChoiceField(queryset=Game.objects.none())
    kind = forms.ChoiceField(choices=KIND_CHOICES, initial="main")
    note = forms.CharField(required=False)

    def __init__(self, *args, library, facts=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["game"].queryset = Game.objects.for_library(library)
        self.state_opener_facts(facts)


def _query(text: str) -> QueryDict:
    return QueryDict(text)


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(username="owner", password="p")


@pytest.fixture
def game(owner):
    return Game.objects.create(library=owner.library, name="Owned")


@pytest.fixture
def foreign_game(django_user_model):
    other = django_user_model.objects.create_user(username="other", password="p")
    return Game.objects.create(library=other.library, name="Foreign")


def _warnings(caplog):
    return [
        record
        for record in caplog.records
        if record.name == "games.opener_facts" and record.levelname == "WARNING"
    ]


def test_a_stated_fact_is_fixed_and_stated(owner, game):
    form = GameFactsForm(
        library=owner.library, facts=_query(f"game={game.id}&kind=dlc")
    )

    assert form.facts == {"game": Fixed(game, "Owned"), "kind": Fixed("dlc", "DLC")}
    assert form.stated("game", Game) == game
    assert form.fields["game"].disabled
    assert form.fields["kind"].disabled
    assert form["kind"].initial == "dlc"


def test_no_facts_leave_the_form_alone(owner):
    form = GameFactsForm(library=owner.library)

    assert form.facts == {}
    assert form.stated("game", Game) is None
    assert not form.fields["kind"].disabled


def test_an_undeclared_parameter_is_ignored(owner):
    form = GameFactsForm(
        library=owner.library, facts=_query("note=hello&origin=/tracker/")
    )

    assert form.facts == {}
    assert form["note"].initial is None


@pytest.mark.parametrize(
    "query",
    ["kind=", "kind=main&kind=dlc", "kind=expansion"],
    ids=["empty", "two values", "unknown word"],
)
def test_a_malformed_choice_leaves_the_field_editable(
    owner, capture_games_logger, query
):
    with capture_games_logger() as caplog:
        form = GameFactsForm(library=owner.library, facts=_query(query))

    assert not form.fields["kind"].disabled
    assert form["kind"].initial == "main"
    assert form.facts == {"kind": Refused(refusal_sentence("Kind"))}
    assert len(_warnings(caplog)) == 1


@pytest.mark.parametrize(
    "raw",
    ["not-a-uuid", str(uuid.uuid4())],
    ids=["text", "version 4"],
)
def test_a_malformed_key_leaves_the_picker_editable(owner, capture_games_logger, raw):
    with capture_games_logger() as caplog:
        form = GameFactsForm(library=owner.library, facts=_query(f"game={raw}"))

    assert not form.fields["game"].disabled
    assert form.facts == {"game": Refused(refusal_sentence("Game"))}
    assert len(_warnings(caplog)) == 1


def test_a_long_value_is_cut_in_the_log(owner, capture_games_logger):
    with capture_games_logger() as caplog:
        GameFactsForm(library=owner.library, facts=_query("kind=" + "x" * 500))

    (warning,) = _warnings(caplog)
    assert "x" * 81 not in warning.getMessage()


def test_refusal_sentence_names_the_field():
    assert refusal_sentence("Game") == (
        "The link named a game this form cannot use. Pick one."
    )


@pytest.mark.parametrize("which", ["unknown", "foreign"])
def test_an_absent_row_leaves_the_picker_editable(
    owner, foreign_game, capture_games_logger, which
):
    key = uuid.uuid7() if which == "unknown" else foreign_game.id

    with capture_games_logger() as caplog:
        form = GameFactsForm(library=owner.library, facts=_query(f"game={key}"))

    assert not form.fields["game"].disabled
    assert form.facts == {"game": Refused(refusal_sentence("Game"))}
    assert len(_warnings(caplog)) == 1


def test_an_absent_row_on_post_keeps_the_input(
    owner, foreign_game, capture_games_logger
):
    with capture_games_logger() as caplog:
        form = GameFactsForm(
            {"game": str(foreign_game.id), "kind": "dlc", "note": "kept"},
            library=owner.library,
            facts=_query(f"game={foreign_game.id}"),
        )

        assert not form.is_valid()

    assert not form.fields["game"].disabled
    assert isinstance(form.facts["game"], Refused)
    assert [error.code for error in form.errors.as_data()["game"]] == ["invalid_choice"]
    assert form.cleaned_data["note"] == "kept"
    assert form.cleaned_data["kind"] == "dlc"
    assert len(_warnings(caplog)) == 1


def test_a_tampered_post_cleans_to_the_fact(owner, game):
    other = Game.objects.create(library=owner.library, name="Other")
    form = GameFactsForm(
        {"game": str(other.id), "kind": "dlc"},
        library=owner.library,
        facts=_query(f"game={game.id}&kind=main"),
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["game"] == game
    assert form.cleaned_data["kind"] == "main"


def test_an_implied_fact_has_no_statement(owner):
    form = GameFactsForm(library=owner.library)
    form.fix_field("kind", "main")

    assert form.facts == {"kind": Fixed("main", None)}
    assert form.fields["kind"].disabled


def test_stating_after_a_bound_field_is_read_raises(owner):
    class EagerForm(GameFactsForm):
        def state_opener_facts(self, facts):
            self["kind"].initial  # noqa: B018
            super().state_opener_facts(facts)

    with pytest.raises(RuntimeError):
        EagerForm(library=owner.library, facts=_query("kind=dlc"))


def test_stating_twice_raises(owner):
    form = GameFactsForm(library=owner.library)

    with pytest.raises(RuntimeError):
        form.state_opener_facts(_query("kind=dlc"))


def test_a_stated_value_of_another_type_raises(owner, game):
    form = GameFactsForm(library=owner.library, facts=_query(f"game={game.id}"))

    with pytest.raises(TypeError):
        form.stated("game", str)


def test_a_fact_named_origin_is_refused(db):
    with pytest.raises(ValueError):
        action_url("games:add_game", origin=None, facts={"origin": "/x"})


GAME_ID = "018f5e66-e800-7000-8000-000000000001"


def test_action_url_writes_facts_beside_the_origin(db):
    url = action_url("games:add_session", origin="/tracker/", facts={"game": GAME_ID})

    assert url == (
        reverse("games:add_session") + f"?game={GAME_ID}&origin=%2Ftracker%2F"
    )


def test_action_url_writes_facts_without_an_origin(db):
    url = action_url("games:add_game", origin=None, facts={"kind": "main"})

    assert url == reverse("games:add_game") + "?kind=main"


def _render(form, **kwargs) -> str:
    return str(FormFields(form, **kwargs))


def _carrier(html: str, name: str) -> str:
    match = re.search(rf'<input[^>]*name="{name}"[^>]*>', html)
    assert match, html
    return match.group(0)


def test_a_stated_fact_renders_a_row_in_place_of_its_control(owner, game):
    form = GameFactsForm(library=owner.library, facts=_query("kind=dlc"))

    html = _render(form)

    row = re.search(r'<div data-field-row="kind">.*?</div>', html, re.DOTALL)
    assert row, html
    assert "<dt" in row.group(0) and ">Kind</dt>" in row.group(0)
    assert "DLC</dd>" in row.group(0)
    carrier = _carrier(html, "kind")
    assert 'type="hidden"' in carrier
    assert 'value="dlc"' in carrier
    assert "disabled" not in carrier
    assert "<select" not in row.group(0)
    assert "None" not in html
    assert "<dd></dd>" not in html
    assert html.index('data-field-row="game"') < html.index('data-field-row="kind"')


def test_a_stated_row_carries_the_key_of_its_row(owner, game):
    form = GameFactsForm(library=owner.library, facts=_query(f"game={game.id}"))

    carrier = _carrier(_render(form), "game")

    assert f'value="{game.id}"' in carrier
    assert "disabled" not in carrier


def test_a_grouped_form_renders_the_stated_row(owner):
    form = GameFactsForm(library=owner.library, facts=_query("kind=dlc"))

    html = _render(
        form,
        groups=[
            FormFieldGroup(legend="What", fields=["kind"]),
            FormFieldGroup(legend="Rest", fields=["game", "note"]),
        ],
    )

    assert "<legend" in html and ">What</legend>" in html
    assert "DLC</dd>" in html
    assert "disabled" not in _carrier(html, "kind")


def test_an_implied_fact_renders_its_carrier_alone(owner):
    form = GameFactsForm(library=owner.library)
    form.fix_field("kind", "main")

    html = _render(form)

    assert 'data-field-row="kind"' not in html
    carrier = _carrier(html, "kind")
    assert 'type="hidden"' in carrier and 'value="main"' in carrier


def test_an_implied_fact_drops_out_of_its_group(owner):
    form = GameFactsForm(library=owner.library)
    form.fix_field("kind", "main")

    html = _render(form, groups=[FormFieldGroup(legend="What", fields=["kind"])])

    assert ">What</legend>" not in html
    assert 'value="main"' in _carrier(html, "kind")


def test_a_refused_fact_says_so_after_its_control(owner, capture_games_logger):
    with capture_games_logger():
        form = GameFactsForm(library=owner.library, facts=_query("kind=expansion"))

    html = _render(form)

    row = re.search(
        r'<div data-field-row="kind">.*?</select>(.*?)</div>', html, re.DOTALL
    )
    assert row, html
    assert refusal_sentence("Kind") in row.group(1)


def test_errors_on_a_stated_field_show_in_its_row(owner):
    form = GameFactsForm({}, library=owner.library, facts=_query("kind=dlc"))
    form.is_valid()
    form.add_error("kind", "Kind refused.")

    row = re.search(
        r'<div data-field-row="kind">.*?Kind refused\..*?</div>',
        _render(form),
        re.DOTALL,
    )

    assert row


def test_errors_on_an_implied_field_join_the_form_errors(owner):
    form = GameFactsForm({}, library=owner.library)
    form.fix_field("kind", "main")
    form.is_valid()
    form.add_error("kind", "Kind refused.")

    html = _render(form)

    assert "Kind refused." in html
    assert html.index("Kind refused.") < html.index('data-field-row="game"')


def test_both_field_box_looks_share_their_size():
    for look in ("editable", "fixed"):
        assert field_box_class("full", look=look).startswith(FIELD_BOX_SHAPE_CLASS)


def test_every_plus_states_what_its_form_takes():
    """A literal a form does not declare does nothing."""
    from django.urls import resolve

    import games.forms as game_forms
    from common.components.search_select import DialogCreate

    forms_by_view = {"add_game": game_forms.GameForm}
    for value in vars(game_forms).values():
        if not isinstance(value, DialogCreate) or not value.literal_query():
            continue
        form = forms_by_view[resolve(str(value.url)).url_name]
        assert set(value.literal_query()) <= set(form.opener_fields)
