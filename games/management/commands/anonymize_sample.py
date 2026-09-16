import copy
import gzip
import random
import tempfile
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import yaml
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from games.events.playersession import (
    day_from_text,
    day_text,
    instant_from_text,
    instant_text,
)
from games.events.references import capture_reference
from games.events.vocabulary import DatedKeys, KeyPath
from games.events.wiring import DEFAULT_WIRING
from games.management.commands.load_sample_data import TARGET_LIBRARY_MARKER
from games.models import (
    Device,
    FilterPreset,
    Game,
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    Platform,
    PlayerGame,
    PlayerSession,
    Playthrough,
    Purchase,
)
from timetracker.temporal import TemporalPrecision, TemporalValue
from timetracker.uuidv7 import UUIDv7Field, uuid7_at

# DB-computed columns: the serializer emits them, loaddata discards them.
# Stripped to keep the fixture clean.
GENERATED_FIELDS = frozenset(["price_per_game"])
PORTABLE_LIBRARY_MODELS = frozenset(
    [
        "games.device",
        "games.game",
        "games.purchase",
        "games.filterpreset",
        "games.libraryeventstreamhead",
        "games.libraryevent",
        "games.libraryeventreference",
    ]
)

# Dumped models, dependencies first (Game before its FK referrers,
# LibraryEventStreamHead before LibraryEvent before LibraryEventReference).
# Omitted: FilterPreset (sample data does not ship personal saved searches).
DUMP_LABELS = [
    "games.Platform",
    "games.Device",
    "games.Game",
    "games.Purchase",
    "games.LibraryEventStreamHead",
    "games.LibraryEvent",
    "games.LibraryEventReference",
    "games.ExchangeRate",
]

# Deterministic stand-in for audit timestamps with no natural date to derive from.
FIXED_EPOCH = datetime(2020, 1, 1, tzinfo=UTC)

MAX_GAMES_PER_PURCHASE = 10
JITTER_DAYS = 365
CONVERSION_RATE = 23.0

# Gitignored map of real game name -> replacement, applied at generation so
# sensitive titles never enter the committed fixture. Absent = no-op.
DEFAULT_NAME_OVERRIDES = (
    Path(__file__).resolve().parents[2] / "fixtures" / "name_overrides.yaml"
)


# The dumped models carrying a uuid, parents first. FilterPreset is absent:
# never dumped. The three event models are also absent: their identities
# derive from recorded_at, not created_at, and from each other's grouping
# (aggregate/correlation/stream), so they get their own dedicated pass in
# _reassign_event_identities rather than this generic one.
IDENTITY_MODELS = (Platform, Device, Game, Purchase)
#: Each model's old identity to its new one.
type Replacements = Mapping[UUID, UUID]
type ReplacementsByModel = Mapping[type, Replacements]

_UUID_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_RAND_B_BITS = 62


def _midnight(date_value):
    return datetime(date_value.year, date_value.month, date_value.day, tzinfo=UTC)


def _floor_ms(moment):
    elapsed = moment - _UUID_EPOCH
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1000
        + elapsed.microseconds // 1000
    )


def _shift_effective_time(value, offset):
    """Shift a day-precision temporal value; leave an unknown one alone.

    The conversion passes (#684, #1038) only ever wrote a day value or an
    unknown one, so those are the only two shapes this command needs to
    handle. Any other precision raises rather than shipping an unjittered
    date.
    """
    if value is None:
        return None
    if value.precision is not TemporalPrecision.DAY:
        raise CommandError(
            f"Event states a {value.precision} value ({value.canonical!r}); "
            "the anonymizer only knows how to shift a day value."
        )
    return TemporalValue.from_day(value.lower_bound + offset, qualifier=value.qualifier)


def _read_path(payload: Mapping, path: KeyPath):
    """The value at `path`, or None where a key is absent or null."""
    value = payload
    for key in path:
        if not isinstance(value, Mapping) or value.get(key) is None:
            return None
        value = value[key]
    return value


def _write_path(payload: dict, path: KeyPath, value) -> None:
    container = payload
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = value


def shift_instant(text: str, *, days: int, zone: str) -> str:
    """Move an instant `days` calendar days at the same wall time in `zone`.

    So the day the instant falls on in that zone moves by exactly
    `days`, across a daylight-saving change as well.
    """
    local = instant_from_text(text).astimezone(ZoneInfo(zone))
    moved = local.replace(tzinfo=None) + timedelta(days=days)
    return instant_text(moved.replace(tzinfo=ZoneInfo(zone)).astimezone(UTC))


def shift_dated(payload: dict, keys: DatedKeys, *, days: int) -> dict:
    """A copy with every stated day and instant moved `days` days.

    A day moves as a date. An instant moves at its wall time in the
    zone stated beside it: the container's `day_zone`, else its own
    `<key>_zone`, else UTC. Where a container states both a start
    and an end, the end is the moved start plus the original
    elapsed time, so a duration survives the move.
    """
    shifted = copy.deepcopy(payload)
    for path in keys.days:
        text = _read_path(shifted, path)
        if text is not None:
            _write_path(
                shifted, path, day_text(day_from_text(text) + timedelta(days=days))
            )
    ends_after_starts: list[tuple[KeyPath, KeyPath]] = []
    for path in keys.instants:
        text = _read_path(shifted, path)
        if text is None:
            continue
        container_path, key = path[:-1], path[-1]
        container = _read_path(shifted, container_path) if container_path else shifted
        if key == "ended_at" and container.get("started_at") is not None:
            ends_after_starts.append(((*container_path, "started_at"), path))
            continue
        zone = container.get("day_zone") or container.get(f"{key}_zone") or "UTC"
        _write_path(shifted, path, shift_instant(text, days=days, zone=zone))
    for start_path, end_path in ends_after_starts:
        elapsed = instant_from_text(_read_path(payload, end_path)) - instant_from_text(
            _read_path(payload, start_path)
        )
        _write_path(
            shifted,
            end_path,
            instant_text(instant_from_text(_read_path(shifted, start_path)) + elapsed),
        )
    return shifted


class Command(BaseCommand):
    help = (
        "Regenerate games/fixtures/sample.yaml.gz from the currently-loaded database "
        "(a production copy), anonymizing the sensitive parts so the result is safe "
        "to commit. Randomizes prices, game<->purchase links, and dates (per-game "
        "offset), clears free-text notes, and sanitizes audit timestamps. All "
        "mutation happens inside a rolled-back transaction, so the source database is "
        "never modified.\n\n"
        "Workflow: restore a production dump into a dedicated PostgreSQL database, "
        "set DATABASE_URL to it, run `make migrate`, then run this command for one "
        "explicit User.\n\n"
        "Residual (accepted) traits of the output: cross-model dates are incoherent "
        "(a session can predate its game's purchase, dates may be in the future); row "
        "counts, per-platform split, currency multiset, real ExchangeRate rows and "
        "preserved playtimes remain a distributional fingerprint. Fixture keeps prod "
        "pks; load_sample_data rejects collisions instead of overwriting rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            required=True,
            help="Existing User whose library is exported.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Seed the RNG for reproducible, byte-identical output.",
        )
        parser.add_argument(
            "--output",
            type=Path,
            default=Path(__file__).resolve().parents[2] / "fixtures" / "sample.yaml.gz",
            help=(
                "Destination fixture path, gzip-compressed "
                "(default: games/fixtures/sample.yaml.gz)."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite the output file if it already exists.",
        )
        parser.add_argument(
            "--scrub-devices",
            action="store_true",
            help="Replace device names with stable 'Device 1', 'Device 2', … labels.",
        )
        parser.add_argument(
            "--name-overrides",
            type=Path,
            default=DEFAULT_NAME_OVERRIDES,
            help=(
                "Path to a gitignored YAML mapping of real game name -> "
                "replacement, applied at generation. No-op if the file is absent."
            ),
        )

    def handle(self, *args, **options):
        output_path = options["output"]
        if output_path.exists() and not options["force"]:
            raise CommandError(
                f"{output_path} already exists; pass --force to overwrite it."
            )
        if options["seed"] is not None:
            random.seed(options["seed"])

        user_model = get_user_model()
        try:
            user = user_model.objects.select_related("library").get(
                username=options["user"]
            )
        except user_model.DoesNotExist as error:
            raise CommandError(f"User {options['user']!r} does not exist.") from error
        library = user.library
        #: Every game the library holds, removed rows included -- the plain
        #: manager, not `for_library()`, whose `alive()` drops them. A removed
        #: game keeps its PlayerGame, its Playthroughs and every LibraryEvent
        #: naming them, and each of those rows is shifted by *its* game's
        #: offset, so an offset is owed per game rather than per live game.
        #: This is also exactly the set `_prune_other_libraries` leaves
        #: behind: `exclude(library=library)` takes the shared
        #: (library-is-null) catalog rows with it.
        all_game_ids = list(
            Game.objects.filter(library=library)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        #: The games a purchase may be pointed at, which is the live ones
        #: only: a purchase is live while any of its games is, so links
        #: reassigned onto removed games would drop the purchase out of every
        #: list the fixture feeds.
        reassignable_game_ids = list(
            Game.objects.for_library(library)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        if not reassignable_game_ids and Purchase.objects.for_library(library).exists():
            raise CommandError("Purchases exist but no games to reassign them to.")

        name_overrides = self._load_overrides(options["name_overrides"])

        with tempfile.TemporaryDirectory() as tempdir:
            dump_path = Path(tempdir) / "dump.yaml"
            with transaction.atomic():
                self._prune_other_libraries(library)
                counts = self._anonymize(
                    all_game_ids,
                    reassignable_game_ids,
                    options["scrub_devices"],
                    name_overrides,
                    library_id=library.pk,
                )
                call_command(
                    "dumpdata",
                    *DUMP_LABELS,
                    format="yaml",
                    indent=2,
                    output=str(dump_path),
                )
                transaction.set_rollback(True)
            self._write_fixture(dump_path, output_path, library_id=library.pk)

        self.stdout.write(
            self.style.SUCCESS(
                "Wrote anonymized fixture to "
                f"{output_path}: "
                + ", ".join(f"{count} {name}" for name, count in counts.items())
            )
        )

    @staticmethod
    def _prune_other_libraries(library):
        """Hide every other library from dumpdata inside the rollback-only copy.

        The three event-store models go before Game, Platform and Device:
        while another library's LibraryEventReference rows still name those
        rows, the pre_delete guard in games/signals.py refuses to delete them.
        """
        FilterPreset.objects.exclude(library=library).delete()
        LibraryEventReference.objects.exclude(library=library).delete()
        LibraryEvent.objects.exclude(library=library).delete()
        LibraryEventStreamHead.objects.exclude(library=library).delete()
        Purchase.objects.exclude(library=library).delete()
        Game.objects.exclude(library=library).delete()
        Device.objects.exclude(library=library).delete()
        Platform.objects.filter(library__isnull=False).exclude(library=library).delete()

    def _anonymize(
        self,
        all_game_ids,
        reassignable_game_ids,
        scrub_devices,
        name_overrides,
        *,
        library_id,
    ):
        game_offsets = {
            game_id: timedelta(days=random.randint(-JITTER_DAYS, JITTER_DAYS))
            for game_id in all_game_ids
        }

        purchases = list(Purchase.objects.order_by("pk"))
        through_rows = []
        Through = Purchase.games.through
        Through.objects.all().delete()
        for purchase in purchases:
            offset = timedelta(days=random.randint(-JITTER_DAYS, JITTER_DAYS))
            purchase.date_purchased += offset
            if purchase.date_refunded is not None:
                purchase.date_refunded += offset
            purchase.price = round(random.uniform(0, 100), 2)
            purchase.converted_price = round(purchase.price * CONVERSION_RATE, 2)
            purchase.converted_currency = "CZK"
            purchase.needs_price_update = False
            purchase.name = ""
            if purchase.type != Purchase.GAME:
                purchase.related_game_id = random.choice(reassignable_game_ids)
            count = random.randint(
                1, min(MAX_GAMES_PER_PURCHASE, len(reassignable_game_ids))
            )
            chosen = random.sample(reassignable_game_ids, count)
            through_rows.extend(
                Through(purchase_id=purchase.pk, game_id=game_id) for game_id in chosen
            )
            purchase.num_purchases = count
            purchase.created_at = _midnight(purchase.date_purchased)
            purchase.updated_at = purchase.created_at
        Through.objects.bulk_create(through_rows)
        Purchase.objects.bulk_update(
            purchases,
            [
                "date_purchased",
                "date_refunded",
                "price",
                "converted_price",
                "converted_currency",
                "needs_price_update",
                "name",
                "related_game",
                "num_purchases",
                "created_at",
                "updated_at",
            ],
        )

        if name_overrides:
            renamed = list(Game.objects.filter(name__in=name_overrides).order_by("pk"))
            for game in renamed:
                game.name = name_overrides[game.name]
            Game.objects.bulk_update(renamed, ["name"])

        Game.objects.update(created_at=FIXED_EPOCH, updated_at=FIXED_EPOCH)
        Platform.objects.update(created_at=FIXED_EPOCH)
        Device.objects.update(created_at=FIXED_EPOCH)
        if scrub_devices:
            devices = list(Device.objects.order_by("pk"))
            for ordinal, device in enumerate(devices, start=1):
                device.name = f"Device {ordinal}"
            Device.objects.bulk_update(devices, ["name"])

        #: Captured before _reassign_uuids remaps PlayerGame.game_id /
        #: Playthrough.player_game__game_id to their new uuids -- game_offsets
        #: is keyed by the original game ids, and this mapping must agree.
        game_id_by_aggregate = {
            **dict(PlayerGame.objects.values_list("pk", "game_id")),
            **dict(Playthrough.objects.values_list("pk", "player_game__game_id")),
            **dict(
                PlayerSession.objects.values_list(
                    "pk", "playthrough__player_game__game_id"
                )
            ),
        }

        replacements_by_model = self._reassign_uuids()
        event_count, session_count = self._reassign_event_identities(
            game_offsets,
            game_id_by_aggregate,
            replacements_by_model,
            library_id=library_id,
        )

        return {
            "games": len(all_game_ids),
            "purchases": len(purchases),
            "sessions": session_count,
            "events": event_count,
        }

    def _reassign_uuids(self):
        """Re-derive every dumped uuid from the dates this command just wrote.

        A UUIDv7 embeds its creation millisecond, so uuids carried over from the
        source database would publish the very timestamps the randomisation
        exists to hide, and would order against the rewritten `created_at`
        rather than with it.

        Runs last, after every date rewrite, and inside the same rolled-back
        transaction. Foreign keys here are DEFERRABLE INITIALLY DEFERRED and the
        transaction never commits, so a parent's uuid can change before its
        children are pointed at the new value.

        Returns the per-model replacement maps, so _reassign_event_identities
        can re-capture a Game reference inside a payload at its final uuid.
        """
        replacements_by_model = {}
        for model in IDENTITY_MODELS:
            replacements = self._resequence_identity(model)
            self._remap_referrers(model, replacements)
            replacements_by_model[model] = replacements
        return replacements_by_model

    @staticmethod
    def _reassign_event_identities(
        game_offsets, game_id_by_aggregate, replacements_by_model, *, library_id
    ):
        """Shift, blank and re-key every event, then re-derive every
        event-table identity from the recorded_at values this method just
        wrote. Runs after _reassign_uuids, whose replacement maps this needs
        to re-capture a payload reference at the row's final uuid.

        game_id_by_aggregate is captured by the caller before _reassign_uuids
        remaps the projections' game columns -- it must agree with
        game_offsets' original-game-id keys, not the post-remap ones a fresh
        query here would return.

        An aggregate keyed on the library itself (the calendar) belongs to
        no game: it takes no offset, keeps its id for `_write_fixture` to
        turn into the owner marker, and is left out of the re-minting.

        Answers the event count and the count of sessions recorded.
        """
        event_types = DEFAULT_WIRING.event_types
        kinds = event_types.reference_kinds
        #: Aggregate order, so an undated event finds its dated predecessor.
        events = list(LibraryEvent.objects.order_by("aggregate_id", "sequence"))
        last_dated_day: dict[UUID, date] = {}
        sessions_recorded = 0
        for event in events:
            library_keyed = event.aggregate_id == library_id
            offset = (
                timedelta(0)
                if library_keyed
                else game_offsets[game_id_by_aggregate[event.aggregate_id]]
            )
            event.effective_time = _shift_effective_time(event.effective_time, offset)
            if event.effective_time is not None:
                last_dated_day[event.aggregate_id] = event.effective_time.lower_bound
            #: An undated event follows the aggregate's latest dated one, so
            #: a removal never precedes the creation it removes.
            day = last_dated_day.get(event.aggregate_id)
            event.recorded_at = FIXED_EPOCH if day is None else _midnight(day)
            payload = shift_dated(
                event.payload,
                event_types.dated_keys(event.event_type),
                days=offset.days,
            )
            if "note" in payload:
                payload["note"] = ""
            if "name" in payload:
                payload["name"] = ""
            for found in event_types.references_in(event.event_type, payload):
                kind = kinds.kind_for(found.value["kind"])
                replacements = replacements_by_model.get(kind.model, {})
                old_id = UUID(found.value["id"])
                payload[found.key] = capture_reference(
                    kind.model.objects.get(pk=replacements.get(old_id, old_id))
                )
            event.payload = payload
            #: Evidence of the source rows: real instants, real keys.
            event.source_metadata = {}
            event.idempotency_key = f"sample:{event.sequence}"
            event.actor = None
            if event.event_type == "library.playersession.created":
                sessions_recorded += 1
        LibraryEvent.objects.bulk_update(
            events,
            [
                "effective_time",
                "recorded_at",
                "payload",
                "source_metadata",
                "idempotency_key",
                "actor",
            ],
        )

        references = list(LibraryEventReference.objects.order_by("pk"))
        for reference in references:
            replacements = replacements_by_model.get(
                kinds.kind_for(reference.kind).model, {}
            )
            reference.referenced_id = replacements.get(
                reference.referenced_id, reference.referenced_id
            )
        LibraryEventReference.objects.bulk_update(references, ["referenced_id"])

        def _mint(moment, state):
            current_ms = _floor_ms(moment)
            state["sequence"] = (
                state["sequence"] + 1 if current_ms == state["ms"] else 0
            )
            state["ms"] = current_ms
            return uuid7_at(
                moment,
                sequence=state["sequence"],
                entropy=random.getrandbits(_RAND_B_BITS),
            )

        def _group_replacements(rows, key):
            """One new id per distinct group, minted at that group's earliest
            recorded_at, in recorded_at order so two groups born in the same
            millisecond still get distinct sequence numbers."""
            earliest = {}
            for row in rows:
                group = key(row)
                if group not in earliest or row.recorded_at < earliest[group]:
                    earliest[group] = row.recorded_at
            state = {"ms": None, "sequence": -1}
            return {
                group: _mint(moment, state)
                for group, moment in sorted(earliest.items(), key=lambda pair: pair[1])
            }

        aggregate_replacements = _group_replacements(
            [event for event in events if event.aggregate_id != library_id],
            lambda event: event.aggregate_id,
        )
        correlation_replacements = _group_replacements(
            events, lambda event: event.correlation_id
        )
        #: LibraryEventStreamHead.id is deliberately left alone.
        #: games_libraryevent's composite FK to it
        #: (library_event_stream_matches_library) is a plain RunSQL
        #: constraint with no DEFERRABLE -- unlike every other FK this
        #: command remaps, Postgres checks it immediately on each UPDATE, so
        #: LibraryEvent.stream_id and LibraryEventStreamHead.id cannot be
        #: swapped to new values in separate statements without one side
        #: transiently naming a row the other doesn't have yet. The residual
        #: leak (the stream head's own uuid still encodes its real creation
        #: millisecond) is far smaller than what this command's jitter
        #: actually targets -- play dates, prices, notes -- so it is accepted
        #: rather than worked around.

        event_moment_by_old_id = {event.pk: event.recorded_at for event in events}
        event_id_replacements = {}
        id_state = {"ms": None, "sequence": -1}
        for event in sorted(events, key=lambda event: (event.recorded_at, event.pk)):
            event_id_replacements[event.pk] = _mint(event.recorded_at, id_state)
        #: bulk_update() refuses primary key fields, so the non-pk fields are
        #: written first (while .pk still matches the pre-reassignment row),
        #: and each event's own id is swapped after via a per-row UPDATE --
        #: the same split _resequence_identity/_remap_referrers already use.
        for event in events:
            event.aggregate_id = aggregate_replacements.get(
                event.aggregate_id, event.aggregate_id
            )
            event.correlation_id = correlation_replacements[event.correlation_id]
            if event.causation_id is not None:
                event.causation_id = correlation_replacements.get(
                    event.causation_id, event.causation_id
                )
            #: A bare aggregate id in a payload names a row whose own
            #: aggregate_id was just re-minted above.
            payload = copy.deepcopy(event.payload)
            for path in event_types.aggregate_id_keys(event.event_type):
                named = _read_path(payload, path)
                if named is not None:
                    old_id = UUID(named)
                    _write_path(
                        payload, path, str(aggregate_replacements.get(old_id, old_id))
                    )
            event.payload = payload
        LibraryEvent.objects.bulk_update(
            events, ["aggregate_id", "correlation_id", "causation_id", "payload"]
        )
        for old_id, new_id in event_id_replacements.items():
            LibraryEvent.objects.filter(pk=old_id).update(id=new_id)

        reference_id_state = {"ms": None, "sequence": -1}
        reference_id_replacements = {}
        for reference in sorted(
            references, key=lambda reference: event_moment_by_old_id[reference.event_id]
        ):
            reference_id_replacements[reference.pk] = _mint(
                event_moment_by_old_id[reference.event_id], reference_id_state
            )
            reference.event_id = event_id_replacements[reference.event_id]
        LibraryEventReference.objects.bulk_update(references, ["event_id"])
        for old_id, new_id in reference_id_replacements.items():
            LibraryEventReference.objects.filter(pk=old_id).update(id=new_id)

        return len(events), sessions_recorded

    @staticmethod
    def _identity_field_name(model) -> str:
        """The name of the UUIDv7 column this command re-derives for `model`.

        `id` once the model's identity has been promoted to its primary key,
        `uuid` while it is still a secondary column. Resolving it per model —
        rather than spelling "uuid" — is what lets one code path serve both
        sides of the identity cutover.
        """
        return "id" if isinstance(model._meta.pk, UUIDv7Field) else "uuid"

    @classmethod
    def _resequence_identity(cls, model):
        """Assign uuids encoding `created_at`, ordered and sequenced like 0005.

        Entropy comes from the seeded RNG rather than `secrets`, which is what
        keeps the output byte-identical for a given --seed.
        """
        identity = cls._identity_field_name(model)
        rows = list(model.objects.order_by("created_at", "pk"))
        replacements = {}
        previous_ms = None
        sequence = 0
        for row in rows:
            current_ms = _floor_ms(row.created_at)
            sequence = sequence + 1 if current_ms == previous_ms else 0
            previous_ms = current_ms
            replacement = uuid7_at(
                row.created_at,
                sequence=sequence,
                entropy=random.getrandbits(_RAND_B_BITS),
            )
            replacements[getattr(row, identity)] = replacement
        # One UPDATE per row rather than bulk_update: the latter refuses a
        # primary-key field outright, which is what `identity` is for a promoted
        # model. A queryset update writes either.
        for original, replacement in replacements.items():
            model.objects.filter(**{identity: original}).update(
                **{identity: replacement}
            )
        return replacements

    @staticmethod
    def _through_field_targeting(relation, model):
        """The through model's own foreign key back to `model`."""
        through = getattr(relation, "through", None) or relation.remote_field.through
        return next(
            field
            for field in through._meta.get_fields()
            if field.is_relation and field.concrete and field.related_model is model
        )

    @classmethod
    def _remap_referrers(cls, model, replacements):
        """Point every foreign key naming this model's identity at the new value.

        `get_fields(include_hidden=True)`, not `related_objects`: the latter
        drops relations whose `related_name` ends in "+", which would silently
        strand `UserLibraryPreferences.default_device`.

        Many-to-many relations are walked too, via their through model's own
        foreign key. Whether a relation needs remapping is decided by what it
        targets, never by its kind: an auto-created through references the
        target's primary key, so `Purchase.games` is inert while the identity is
        a secondary column and live once it is the primary key.

        Unmanaged referrers are skipped. A rebuild's shadow twin
        (games/events/targets.py) joins the live registry and stays there for
        the life of the process, hidden relation and all, but its table only
        exists inside the attempt that made it -- so a walk that reads twins
        works until something triggers one rebuild, then fails forever.
        """
        identity = cls._identity_field_name(model)
        for relation in model._meta.get_fields(include_hidden=True):
            if not relation.is_relation or relation.concrete:
                continue
            if relation.many_to_many:
                field = cls._through_field_targeting(relation, model)
            else:
                field = relation.field
            if field.target_field.name != identity:
                continue
            if not field.model._meta.managed:
                continue
            children = list(
                field.model._base_manager.exclude(**{f"{field.attname}__isnull": True})
            )
            for child in children:
                current = getattr(child, field.attname)
                if current in replacements:
                    setattr(child, field.attname, replacements[current])
            field.model._base_manager.bulk_update(
                children, [field.name], batch_size=1000
            )

    def _load_overrides(self, path):
        if not path or not path.exists():
            return {}
        with path.open() as stream:
            mapping = yaml.safe_load(stream) or {}
        return {str(old): str(new) for old, new in mapping.items()}

    def _write_fixture(self, dump_path, output_path, *, library_id):
        with dump_path.open() as stream:
            objects = yaml.safe_load(stream) or []
        for item in objects:
            fields = item.get("fields", {})
            for key in GENERATED_FIELDS:
                fields.pop(key, None)
            if item.get("model") == "games.libraryevent":
                if fields.get("effective_time") == "":
                    fields.pop("effective_time", None)
                #: The calendar's aggregate is the library; the loader
                #: substitutes the owner's.
                if str(fields.get("aggregate_id")) == str(library_id):
                    fields["aggregate_id"] = TARGET_LIBRARY_MARKER
            if item.get("model") in PORTABLE_LIBRARY_MODELS or (
                item.get("model") == "games.platform"
                and fields.get("library") is not None
            ):
                fields["library"] = TARGET_LIBRARY_MARKER
        payload = yaml.safe_dump(
            objects, sort_keys=True, default_flow_style=False
        ).encode()
        # mtime=0 and no embedded filename keep the gzip output byte-identical
        # across runs, so a fixed --seed yields a stable git blob.
        output_path.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
