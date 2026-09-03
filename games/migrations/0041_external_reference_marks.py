from django.db import migrations, models
from django.db.models import OuterRef, Subquery
from django.utils.timezone import now

#: Page size; nothing opens a cursor.
BATCH_SIZE = 500

#: Each kind, and its column.
TARGET_COLUMNS = {
    "game": "game_id",
    "edition": "edition_id",
    "release": "release_id",
    "platform": "platform_id",
}


def _paged(queryset):
    """Page a historical queryset by primary key."""
    last = None
    while True:
        page = queryset if last is None else queryset.filter(id__gt=last)
        rows = list(page.order_by("id")[:BATCH_SIZE])
        if not rows:
            return
        yield from rows
        if len(rows) < BATCH_SIZE:
            return
        last = rows[-1].id


def _mark_references_of_removed_rows(apps, schema_editor):
    """A removed row lets go (#976).

    The mark is the row's own and not this run's clock, because
    `games/removal.py` reads the two back as equal.
    """
    reference_model = apps.get_model("games", "ExternalReference")
    for kind, column in TARGET_COLUMNS.items():
        relation = column.removesuffix("_id")
        target_model = apps.get_model("games", kind)
        reference_model.objects.filter(
            entity_kind=kind,
            removed_at__isnull=True,
            **{f"{relation}__removed_at__isnull": False},
        ).update(
            removed_at=Subquery(
                target_model.objects.filter(id=OuterRef(column)).values("removed_at")[
                    :1
                ]
            )
        )


def _keeper(kind, incumbent, candidate, mirrored):
    """The mirrored key stays, else the earliest."""
    if kind == "game":
        wanted = mirrored.get(incumbent.game_id)
        if wanted is not None:
            if candidate.provider_key == wanted:
                return candidate
            if incumbent.provider_key == wanted:
                return incumbent
    return incumbent if incumbent.id <= candidate.id else candidate


def _keep_one_key_per_record(apps, schema_editor):
    """Two keys of one provider, resolved."""
    reference_model = apps.get_model("games", "ExternalReference")
    game_model = apps.get_model("games", "Game")
    stamped = now()
    mirrored = dict(
        game_model.objects.exclude(wikidata="")
        .exclude(wikidata=None)
        .values_list("id", "wikidata")
    )
    for kind, column in TARGET_COLUMNS.items():
        held = {}
        rows = reference_model.objects.filter(entity_kind=kind, removed_at__isnull=True)
        for reference in _paged(rows):
            slot = (reference.provider, getattr(reference, column))
            incumbent = held.get(slot)
            if incumbent is None:
                held[slot] = reference
                continue
            keeper = _keeper(kind, incumbent, reference, mirrored)
            held[slot] = keeper
            loser = reference if keeper is incumbent else incumbent
            reference_model.objects.filter(pk=loser.pk).update(removed_at=stamped)


def _refuse_a_reverse_that_loses_the_marks(apps, schema_editor):
    """Refuse a reverse while a mark stands.

    Reversing puts the unconditional unique back, which a key one
    record let go of and another now holds would break, with the
    column naming the loser already gone.
    """
    del schema_editor
    reference_model = apps.get_model("games", "ExternalReference")
    if reference_model.objects.filter(removed_at__isnull=False).exists():
        raise RuntimeError(
            "Cannot reverse external reference marks while marked reference rows exist."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0040_edition_name"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="externalreference",
            name="unique_external_reference_provider_kind_key",
        ),
        migrations.AddField(
            model_name="externalreference",
            name="removed_at",
            field=models.DateTimeField(
                blank=True, default=None, editable=False, null=True
            ),
        ),
        #: The guard at the end reverses first.
        migrations.RunPython(
            _mark_references_of_removed_rows, migrations.RunPython.noop
        ),
        migrations.RunPython(_keep_one_key_per_record, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(("removed_at__isnull", True)),
                fields=("provider", "entity_kind", "provider_key"),
                name="unique_external_reference_provider_kind_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("game__isnull", False), ("removed_at__isnull", True)
                ),
                fields=("provider", "game"),
                name="unique_live_game_reference_per_provider",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("edition__isnull", False), ("removed_at__isnull", True)
                ),
                fields=("provider", "edition"),
                name="unique_live_edition_reference_per_provider",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("release__isnull", False), ("removed_at__isnull", True)
                ),
                fields=("provider", "release"),
                name="unique_live_release_reference_per_provider",
            ),
        ),
        migrations.AddConstraint(
            model_name="externalreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("platform__isnull", False), ("removed_at__isnull", True)
                ),
                fields=("provider", "platform"),
                name="unique_live_platform_reference_per_provider",
            ),
        ),
        #: Last, thus first to reverse.
        migrations.RunPython(
            migrations.RunPython.noop, _refuse_a_reverse_that_loses_the_marks
        ),
    ]
