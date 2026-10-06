"""A form states the facts its opener names."""

import re
import uuid

import pytest
from django import forms
from django.http import Http404, QueryDict
from django.urls import reverse

from common.components import FormFieldGroup, FormFields
from common.opener_facts import OpenerFactsMixin, refusal_sentence
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

    assert form.stated_facts == {"game": game, "kind": "dlc"}
    assert form.statements == {"game": "Owned", "kind": "DLC"}
    assert form.fields["game"].disabled
    assert form.fields["kind"].disabled
    assert form["kind"].initial == "dlc"
    assert form.refused_facts == {}


def test_no_facts_leave_the_form_alone(owner):
    form = GameFactsForm(library=owner.library)

    assert form.stated_facts == {}
    assert form.statements == {}
    assert not form.fields["kind"].disabled


def test_an_undeclared_parameter_is_ignored(owner):
    form = GameFactsForm(
        library=owner.library, facts=_query("note=hello&origin=/tracker/")
    )

    assert form.stated_facts == {}
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

    assert "kind" not in form.stated_facts
    assert not form.fields["kind"].disabled
    assert form["kind"].initial == "main"
    assert form.refused_facts == {"kind": refusal_sentence("Kind")}
    assert len(_warnings(caplog)) == 1


@pytest.mark.parametrize(
    "raw",
    ["not-a-uuid", str(uuid.uuid4())],
    ids=["text", "version 4"],
)
def test_a_malformed_key_leaves_the_picker_editable(owner, capture_games_logger, raw):
    with capture_games_logger() as caplog:
        form = GameFactsForm(library=owner.library, facts=_query(f"game={raw}"))

    assert "game" not in form.stated_facts
    assert not form.fields["game"].disabled
    assert "game" in form.refused_facts
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
def test_an_absent_row_on_get_is_404(owner, foreign_game, capture_games_logger, which):
    key = uuid.uuid7() if which == "unknown" else foreign_game.id

    with capture_games_logger() as caplog, pytest.raises(Http404):
        GameFactsForm(library=owner.library, facts=_query(f"game={key}"))

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
    assert "game" in form.refused_facts
    assert [error.code for error in form.errors.as_data()["game"]] == ["invalid_choice"]
    assert form.cleaned_data["note"] == "kept"
    assert form.cleaned_data["kind"] == "dlc"
    assert _warnings(caplog) == []


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

    assert form.stated_facts == {"kind": "main"}
    assert form.statements == {"kind": None}
    assert form.fields["kind"].disabled


def test_stating_after_a_bound_field_is_read_raises(owner):
    class EagerForm(GameFactsForm):
        def state_opener_facts(self, facts):
            self["kind"].initial  # noqa: B018
            super().state_opener_facts(facts)

    with pytest.raises(RuntimeError):
        EagerForm(library=owner.library, facts=_query("kind=dlc"))


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
    assert ">DLC</dd>" in row.group(0)
    carrier = _carrier(html, "kind")
    assert 'type="hidden"' in carrier
    assert 'value="dlc"' in carrier
    assert "disabled" not in carrier
    assert "<select" not in row.group(0)
    assert "None" not in html
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
    assert ">DLC</dd>" in html
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
