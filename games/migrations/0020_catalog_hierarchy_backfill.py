import json
from collections import defaultdict

from django.db import migrations

MACHINE_PREFIX = "CATALOG_HIERARCHY_RECONCILIATION_JSON="
HUMAN_PREFIX = "CAT hierarchy reconciliation:"
BATCH_SIZE = 1000
PRESERVED_GAME_FIELDS = (
    "library_id",
    "name",
    "sort_name",
    "original_year_released",
    "year_released",
    "platform_id",
    "wikidata",
    "status",
    "mastered",
    "playtime",
    "created_at",
    "updated_at",
)
SUMMARY_KEYS = (
    "games",
    "editions",
    "releases",
    "default_editions",
    "default_releases",
    "original_dates_known",
    "original_dates_unknown",
    "release_dates_known",
    "release_dates_unknown",
    "unspecified_platforms",
    "mismatches",
)


def _json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    serialize = getattr(value, "serialize", None)
    if serialize is not None:
        return serialize()
    return str(value)


def _human_value(value):
    return "null" if value is None else str(value)


def _year_value(year):
    return None if year is None else f"{year:04d}"


def _game_snapshot(Game):
    snapshot = {}
    rows = Game.objects.order_by("pk").values("pk", *PRESERVED_GAME_FIELDS)
    for row in rows:
        game_id = str(row.pop("pk"))
        snapshot[game_id] = {key: _json_value(value) for key, value in row.items()}
    return snapshot


def _preflight_mismatches(apps, snapshot):
    Platform = apps.get_model("games", "Platform")
    platform_libraries = {
        str(platform_id): _json_value(library_id)
        for platform_id, library_id in Platform.objects.values_list("pk", "library_id")
    }
    mismatches = []
    for game_id, row in snapshot.items():
        for field, code in (
            ("original_year_released", "invalid_original_year"),
            ("year_released", "invalid_release_year"),
        ):
            year = row[field]
            if year is not None and not 1 <= year <= 9999:
                mismatches.append(
                    {
                        "code": code,
                        "game_id": game_id,
                        "field": field,
                        "expected": "1..9999 or null",
                        "actual": year,
                    }
                )

        platform_id = row["platform_id"]
        platform_library_id = platform_libraries.get(platform_id)
        if (
            platform_id is not None
            and platform_library_id is not None
            and platform_library_id != row["library_id"]
        ):
            mismatches.append(
                {
                    "code": "legacy_platform_cross_library",
                    "game_id": game_id,
                    "platform_id": platform_id,
                    "game_library_id": row["library_id"],
                    "platform_library_id": platform_library_id,
                }
            )
    return mismatches


def _ensure_default_graphs(apps):
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")

    games = list(Game.objects.order_by("pk"))
    for game in games:
        game.original_release_date = _year_value(game.original_year_released)
    if games:
        Game.objects.bulk_update(
            games,
            ["original_release_date"],
            batch_size=BATCH_SIZE,
        )

    default_game_ids = set(
        Edition.objects.filter(is_default=True).values_list("game_id", flat=True)
    )
    new_editions = [
        Edition(game_id=game.pk, is_default=True)
        for game in games
        if game.pk not in default_game_ids
    ]
    if new_editions:
        Edition.objects.bulk_create(new_editions, batch_size=BATCH_SIZE)

    default_editions = list(Edition.objects.filter(is_default=True).order_by("game_id"))
    default_release_edition_ids = set(
        Release.objects.filter(
            is_default=True,
            edition__is_default=True,
        ).values_list("edition_id", flat=True)
    )
    new_releases = [
        Release(edition_id=edition.pk, is_default=True)
        for edition in default_editions
        if edition.pk not in default_release_edition_ids
    ]
    if new_releases:
        Release.objects.bulk_create(new_releases, batch_size=BATCH_SIZE)

    default_releases = list(
        Release.objects.filter(
            is_default=True,
            edition__is_default=True,
        )
        .select_related("edition__game")
        .order_by("edition__game_id")
    )
    for release in default_releases:
        game = release.edition.game
        release.release_date = _year_value(game.year_released)
        release.platform_id = game.platform_id
    if default_releases:
        Release.objects.bulk_update(
            default_releases,
            ["release_date", "platform"],
            batch_size=BATCH_SIZE,
        )
    return len(new_editions), len(new_releases)


def _default_graph_ids(apps):
    Release = apps.get_model("games", "Release")
    rows = (
        Release.objects.filter(
            is_default=True,
            edition__is_default=True,
        )
        .order_by("edition__game_id")
        .values_list("edition__game_id", "edition_id", "pk")
    )
    return tuple(tuple(str(value) for value in row) for row in rows)


def _result_mismatches(
    apps,
    before_snapshot,
    first_graph_ids,
    second_graph_ids,
    second_insert_counts,
):
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    mismatches = []
    current_snapshot = _game_snapshot(Game)
    before_ids = set(before_snapshot)
    current_ids = set(current_snapshot)
    for game_id in sorted(before_ids - current_ids):
        mismatches.append({"code": "missing_game", "game_id": game_id})
    for game_id in sorted(current_ids - before_ids):
        mismatches.append({"code": "extra_game", "game_id": game_id})
    for game_id in sorted(before_ids & current_ids):
        before = before_snapshot[game_id]
        current = current_snapshot[game_id]
        for field in PRESERVED_GAME_FIELDS:
            if before[field] != current[field]:
                mismatches.append(
                    {
                        "code": "preserved_game_field_changed",
                        "game_id": game_id,
                        "field": field,
                        "expected": before[field],
                        "actual": current[field],
                    }
                )

    edition_counts = defaultdict(int)
    for game_id in Edition.objects.filter(is_default=True).values_list(
        "game_id", flat=True
    ):
        edition_counts[str(game_id)] += 1
    for game_id in sorted(before_ids):
        count = edition_counts[game_id]
        if count != 1:
            mismatches.append(
                {
                    "code": "default_edition_count",
                    "game_id": game_id,
                    "expected": 1,
                    "actual": count,
                }
            )

    release_counts = defaultdict(int)
    for edition_id in Release.objects.filter(
        is_default=True,
        edition__is_default=True,
    ).values_list("edition_id", flat=True):
        release_counts[str(edition_id)] += 1
    for edition in Edition.objects.filter(is_default=True).order_by("game_id"):
        count = release_counts[str(edition.pk)]
        if count != 1:
            mismatches.append(
                {
                    "code": "default_release_count",
                    "game_id": str(edition.game_id),
                    "edition_id": str(edition.pk),
                    "expected": 1,
                    "actual": count,
                }
            )

    default_releases = (
        Release.objects.filter(
            is_default=True,
            edition__is_default=True,
        )
        .select_related("edition__game", "platform")
        .order_by("edition__game_id")
    )
    for release in default_releases:
        game = release.edition.game
        game_id = str(game.pk)
        expected_original_date = _year_value(game.original_year_released)
        actual_original_date = _json_value(game.original_release_date)
        if actual_original_date != expected_original_date:
            mismatches.append(
                {
                    "code": "original_date_mismatch",
                    "game_id": game_id,
                    "expected": expected_original_date,
                    "actual": actual_original_date,
                }
            )

        expected_release_date = _year_value(game.year_released)
        actual_release_date = _json_value(release.release_date)
        if actual_release_date != expected_release_date:
            mismatches.append(
                {
                    "code": "release_date_mismatch",
                    "game_id": game_id,
                    "edition_id": str(release.edition_id),
                    "release_id": str(release.pk),
                    "expected": expected_release_date,
                    "actual": actual_release_date,
                }
            )
        if release.platform_id != game.platform_id:
            mismatches.append(
                {
                    "code": "release_platform_mismatch",
                    "game_id": game_id,
                    "edition_id": str(release.edition_id),
                    "release_id": str(release.pk),
                    "expected": _json_value(game.platform_id),
                    "actual": _json_value(release.platform_id),
                }
            )
        if (
            release.platform_id is not None
            and release.platform.library_id is not None
            and release.platform.library_id != game.library_id
        ):
            mismatches.append(
                {
                    "code": "release_platform_cross_library",
                    "game_id": game_id,
                    "edition_id": str(release.edition_id),
                    "release_id": str(release.pk),
                    "platform_id": str(release.platform_id),
                    "game_library_id": str(game.library_id),
                    "platform_library_id": str(release.platform.library_id),
                }
            )

    if second_insert_counts != (0, 0) or first_graph_ids != second_graph_ids:
        mismatches.append(
            {
                "code": "non_idempotent_default_graph",
                "expected": {"inserted": [0, 0], "graph_ids": first_graph_ids},
                "actual": {
                    "inserted": list(second_insert_counts),
                    "graph_ids": second_graph_ids,
                },
            }
        )
    return mismatches


def _summary(apps, mismatch_count):
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    default_releases = Release.objects.filter(
        is_default=True,
        edition__is_default=True,
    )
    return {
        "games": Game.objects.count(),
        "editions": Edition.objects.count(),
        "releases": Release.objects.count(),
        "default_editions": Edition.objects.filter(is_default=True).count(),
        "default_releases": default_releases.count(),
        "original_dates_known": Game.objects.filter(
            original_release_date__isnull=False
        ).count(),
        "original_dates_unknown": Game.objects.filter(
            original_release_date__isnull=True
        ).count(),
        "release_dates_known": default_releases.filter(
            release_date__isnull=False
        ).count(),
        "release_dates_unknown": default_releases.filter(
            release_date__isnull=True
        ).count(),
        "unspecified_platforms": default_releases.filter(platform__isnull=True).count(),
        "mismatches": mismatch_count,
    }


def _mismatch_sort_key(mismatch):
    return tuple(
        str(mismatch.get(key) or "")
        for key in (
            "code",
            "game_id",
            "edition_id",
            "release_id",
            "field",
            "expected",
            "actual",
        )
    )


def _emit(summary, mismatches):
    mismatches = sorted(mismatches, key=_mismatch_sort_key)
    payload = {
        "schema_version": 1,
        "summary": summary,
        "mismatches": mismatches,
    }
    print(MACHINE_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")))
    print(
        HUMAN_PREFIX + " " + " ".join(f"{key}={summary[key]}" for key in SUMMARY_KEYS)
    )
    for mismatch in mismatches:
        details = " ".join(
            f"{key}={_human_value(value)}"
            for key, value in sorted(mismatch.items())
            if key != "code"
        )
        print(
            f"CAT hierarchy mismatch: code={mismatch['code']}"
            + (f" {details}" if details else "")
        )


def _fail_if_mismatched(mismatches):
    if mismatches:
        raise RuntimeError(
            f"CAT hierarchy reconciliation failed with {len(mismatches)} mismatch(es)."
        )


def backfill_catalog_hierarchy(apps, schema_editor):
    del schema_editor
    Game = apps.get_model("games", "Game")
    before_snapshot = _game_snapshot(Game)
    mismatches = _preflight_mismatches(apps, before_snapshot)
    if mismatches:
        _emit(_summary(apps, len(mismatches)), mismatches)
        _fail_if_mismatched(mismatches)

    _ensure_default_graphs(apps)
    first_graph_ids = _default_graph_ids(apps)
    second_insert_counts = _ensure_default_graphs(apps)
    second_graph_ids = _default_graph_ids(apps)
    mismatches = _result_mismatches(
        apps,
        before_snapshot,
        first_graph_ids,
        second_graph_ids,
        second_insert_counts,
    )
    summary = _summary(apps, len(mismatches))
    _emit(summary, mismatches)
    _fail_if_mismatched(mismatches)


class Migration(migrations.Migration):
    dependencies = [("games", "0019_catalog_write_defaults")]

    operations = [
        migrations.RunPython(
            backfill_catalog_hierarchy,
            migrations.RunPython.noop,
        )
    ]
