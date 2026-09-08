"""A saved preset names the run's endpoint.

#1013 renamed `ended` to `completed`. A preset holds the old
word in a criterion, in a games filter's run subtree, and in
a sort token.
"""

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.utils.module_loading import import_string

from games.models import FilterPreset

MIGRATION = "games.migrations.0047_playthrough_preset_completed"


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="preset-owner", password="pw")


@pytest.mark.django_db
def test_the_forward_pass_rewrites_the_criterion_and_the_sort(user):
    preset = FilterPreset.objects.create(
        library=user.library,
        name="Finished",
        mode="playthroughs",
        find_filter={"sort": "-ended,name"},
        object_filter={"ended": {"value": "2025-01-01", "modifier": "EQUALS"}},
        ui_options={},
    )
    rename_forward = import_string(f"{MIGRATION}.rename_forward")

    rename_forward(apps, None)

    preset.refresh_from_db()
    assert preset.object_filter == {
        "completed": {"value": "2025-01-01", "modifier": "EQUALS"}
    }
    #: The sign travels with the token.
    assert preset.find_filter == {"sort": "-completed,name"}


@pytest.mark.django_db
def test_a_run_filter_under_an_operator_is_rewritten(user):
    preset = FilterPreset.objects.create(
        library=user.library,
        name="Either end",
        mode="playthroughs",
        find_filter={},
        object_filter={"OR": [{"ended": {"value": "2025-01-01"}}, {"started": {}}]},
        ui_options={},
    )
    rename_forward = import_string(f"{MIGRATION}.rename_forward")

    rename_forward(apps, None)

    preset.refresh_from_db()
    assert preset.object_filter == {
        "OR": [{"completed": {"value": "2025-01-01"}}, {"started": {}}]
    }


@pytest.mark.django_db
def test_a_games_preset_rewrites_the_run_subtree_alone(user):
    """The walk reaches the run subtree only."""
    preset = FilterPreset.objects.create(
        library=user.library,
        name="Finished games",
        mode="games",
        find_filter={"sort": "-ended"},
        object_filter={
            "ended": {"value": "not a run's word"},
            "AND": [
                {
                    "playthrough_filter": {
                        "ended": {"value": "2025-01-01", "modifier": "EQUALS"}
                    }
                }
            ],
        },
        ui_options={},
    )
    rename_forward = import_string(f"{MIGRATION}.rename_forward")

    rename_forward(apps, None)

    preset.refresh_from_db()
    assert preset.object_filter == {
        "ended": {"value": "not a run's word"},
        "AND": [
            {
                "playthrough_filter": {
                    "completed": {"value": "2025-01-01", "modifier": "EQUALS"}
                }
            }
        ],
    }
    #: A games list sort names no run.
    assert preset.find_filter == {"sort": "-ended"}


@pytest.mark.django_db
def test_a_preset_of_another_mode_is_left_alone(user):
    preset = FilterPreset.objects.create(
        library=user.library,
        name="Long sessions",
        mode="sessions",
        find_filter={"sort": "-ended"},
        object_filter={"ended": {"value": "2025-01-01"}},
        ui_options={},
    )
    rename_forward = import_string(f"{MIGRATION}.rename_forward")

    rename_forward(apps, None)

    preset.refresh_from_db()
    assert preset.object_filter == {"ended": {"value": "2025-01-01"}}
    assert preset.find_filter == {"sort": "-ended"}


@pytest.mark.django_db
def test_the_backward_pass_is_the_inverse(user):
    preset = FilterPreset.objects.create(
        library=user.library,
        name="Finished",
        mode="playthroughs",
        find_filter={"sort": "-completed"},
        object_filter={"completed": {"value": "2025-01-01"}},
        ui_options={},
    )
    rename_backward = import_string(f"{MIGRATION}.rename_backward")

    rename_backward(apps, None)

    preset.refresh_from_db()
    assert preset.object_filter == {"ended": {"value": "2025-01-01"}}
    assert preset.find_filter == {"sort": "-ended"}
