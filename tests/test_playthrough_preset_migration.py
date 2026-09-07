"""The saved presets are rewritten.

#687 renamed the mode key and the two criterion keys, and
a preset holds both as stored strings. The rewrite is a
plain function, so it is tested as one.
"""

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.utils.module_loading import import_string

from games.models import FilterPreset

MIGRATION = "games.migrations.0046_playthrough_preset_mode"


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="preset-owner", password="pw")


def test_a_nested_criterion_key_is_rewritten_at_any_depth():
    rewrite = import_string(f"{MIGRATION}._rewrite")

    rewritten = rewrite(
        {
            "AND": [
                {"playevent_count": {"modifier": "GREATER_THAN", "value": 1}},
                {"OR": [{"playevent_filter": {"note": {"value": "x"}}}]},
            ]
        },
        {
            "playevent_count": "playthrough_count",
            "playevent_filter": "playthrough_filter",
        },
    )

    assert rewritten == {
        "AND": [
            {"playthrough_count": {"modifier": "GREATER_THAN", "value": 1}},
            {"OR": [{"playthrough_filter": {"note": {"value": "x"}}}]},
        ]
    }


@pytest.mark.django_db
def test_the_forward_pass_rewrites_the_mode_and_the_stored_filter(user):
    preset = FilterPreset.objects.create(
        library=user.library,
        name="Long runs",
        mode="playevents",
        find_filter={"sort": "-ended"},
        object_filter={"AND": [{"playevent_count": {"value": 2}}]},
        ui_options={},
    )
    rename_forward = import_string(f"{MIGRATION}.rename_forward")

    rename_forward(apps, None)

    preset.refresh_from_db()
    assert preset.mode == "playthroughs"
    assert preset.object_filter == {"AND": [{"playthrough_count": {"value": 2}}]}


@pytest.mark.django_db
def test_the_backward_pass_is_the_inverse(user):
    preset = FilterPreset.objects.create(
        library=user.library,
        name="Long runs",
        mode="playthroughs",
        find_filter={},
        object_filter={"AND": [{"playthrough_filter": {"note": {"value": "x"}}}]},
        ui_options={},
    )
    rename_backward = import_string(f"{MIGRATION}.rename_backward")

    rename_backward(apps, None)

    preset.refresh_from_db()
    assert preset.mode == "playevents"
    assert preset.object_filter == {
        "AND": [{"playevent_filter": {"note": {"value": "x"}}}]
    }
