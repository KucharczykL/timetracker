import copy
import gzip
import random
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import yaml
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import GeneratedField, Min, Model

from games.events.historical_playtime import sorted_runs
from games.events.playersession import (
    day_from_text,
    day_text,
    instant_from_text,
    instant_text,
)
from games.events.references import (
    FoundReference,
    Reference,
    ReferenceKind,
    Resolution,
    capture_reference,
)
from games.events.vocabulary import DatedKeys, KeyPath, PayloadInvalid
from games.events.wiring import DEFAULT_WIRING
from games.management.commands.load_sample_data import (
    TARGET_LIBRARY_MARKER,
    FixtureLabel,
)
from games.models import (
    Device,
    Edition,
    ExchangeRate,
    FilterPreset,
    Game,
    HistoricalPlaytime,
    LibraryEntry,
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    Platform,
    PlayerGame,
    PlayerSession,
    Playthrough,
    Purchase,
    PurchaseValuation,
    Release,
    UserLibraryPreferences,
)
from games.projections import FieldName, projection_models
from timetracker.temporal import TemporalPrecision, TemporalValue
from timetracker.uuidv7 import UUIDv7Field, uuid7_at

PORTABLE_LIBRARY_MODELS = frozenset(
    [
        "games.game",
        "games.filterpreset",
        "games.libraryeventstreamhead",
        "games.libraryevent",
        "games.libraryeventreference",
    ]
)

# Dumped models, dependencies first (Game before its FK referrers,
# LibraryEventStreamHead before LibraryEvent before LibraryEventReference).
# Omitted: FilterPreset (sample data does not ship personal saved searches).
DUMPED_MODELS: Final[tuple[type[Model], ...]] = (
    Platform,
    Game,
    Edition,
    Release,
    LibraryEventStreamHead,
    LibraryEvent,
    LibraryEventReference,
    ExchangeRate,
)
DUMP_LABELS: Final[tuple[FixtureLabel, ...]] = tuple(
    model._meta.label_lower for model in DUMPED_MODELS
)

#: Serialized by dumpdata, discarded by loaddata.
GENERATED_FIELDS: Final[Mapping[FixtureLabel, frozenset[FieldName]]] = {
    model._meta.label_lower: frozenset(
        field.name
        for field in model._meta.concrete_fields
        if isinstance(field, GeneratedField)
    )
    for model in DUMPED_MODELS
}

# Deterministic stand-in for audit timestamps with no natural date to derive from.
FIXED_EPOCH = datetime(2020, 1, 1, tzinfo=UTC)

JITTER_DAYS = 365

# Gitignored map of real game name -> replacement, applied at generation so
# sensitive titles never enter the committed fixture. Absent = no-op.
DEFAULT_NAME_OVERRIDES = (
    Path(__file__).resolve().parents[2] / "fixtures" / "name_overrides.yaml"
)


#: Re-minted, parents first; events have their own pass.
IDENTITY_MODELS = (Platform, Device, Game, Edition, Release)
#: One payload value, as stored.
type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)
#: Text in, text out.
type LeafRewrite = Callable[[str], str]
#: State one mint sequence carries.
type MintState = dict[str, int | None]
#: The one bare id no aggregate holds.
JOIN_ID_PATH: Final[KeyPath] = ("playthroughs", "id")
#: Twelve bits of counter per millisecond.
_MAX_SEQUENCE = 4095
#: Old identity to new, per model.
type Replacements = Mapping[UUID, UUID]
type ReplacementsByModel = Mapping[type, Replacements]

_UUID_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_RAND_B_BITS = 62


def _mint(moment: datetime, state: MintState) -> UUID:
    """The next id at or after `moment`, in order.

    A full millisecond carries into the next one.
    """
    floor = _floor_ms(moment)
    last = state["ms"]
    current_ms = floor if last is None else max(floor, last)
    sequence = 0
    if current_ms == last:
        sequence = cast(int, state["sequence"]) + 1
        if sequence > _MAX_SEQUENCE:
            current_ms, sequence = current_ms + 1, 0
    state["ms"], state["sequence"] = current_ms, sequence
    return uuid7_at(
        _UUID_EPOCH + timedelta(milliseconds=current_ms),
        sequence=sequence,
        entropy=random.getrandbits(_RAND_B_BITS),
    )


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


def _read_path(payload: Mapping[str, Any], path: KeyPath) -> Any:
    """Value at path; None when absent."""
    value = payload
    for key in path:
        # Dates are never stated inside a list.
        if isinstance(value, list):
            raise CommandError(f"A dated path crosses a list: {path}.")
        if not isinstance(value, Mapping) or value.get(key) is None:
            return None
        value = value[key]
    return value


def _write_path(payload: dict[str, Any], path: KeyPath, value: Any) -> None:
    container = payload
    for key in path[:-1]:
        container = container[key]
    container[path[-1]] = value


def rewrite_path(payload: JsonValue, path: KeyPath, rewrite: LeafRewrite) -> None:
    """Rewrite every value at path, lists included.

    An absent or null value is skipped; a scalar
    where the path goes on is a shape no vocabulary
    states, and is refused rather than left unscrubbed.
    """
    if not path:
        raise ValueError("An empty path names no value.")
    if isinstance(payload, list):
        for item in payload:
            rewrite_path(item, path, rewrite)
        return
    if not isinstance(payload, dict):
        raise CommandError(f"Path {path} meets {payload!r}, not an object.")
    head, rest = path[0], path[1:]
    value = payload.get(head)
    if value is None:
        return
    if rest:
        rewrite_path(value, rest, rewrite)
        return
    if isinstance(value, list):
        payload[head] = [
            None if item is None else _rewrite_text(item, path, rewrite)
            for item in value
        ]
    else:
        payload[head] = _rewrite_text(value, path, rewrite)


def _rewrite_text(value: JsonValue, path: KeyPath, rewrite: LeafRewrite) -> str:
    """Every aliased leaf is text."""
    if not isinstance(value, str):
        raise CommandError(f"Path {path} holds {value!r}, not text.")
    return rewrite(value)


def replace_reference(
    payload: dict[str, Any], found: FoundReference, value: Reference
) -> None:
    """Put `value` where `found` was, in a list too."""
    held = payload[found.key]
    if not isinstance(held, list):
        payload[found.key] = value
        return
    if not any(item is found.value for item in held):
        raise CommandError(f"Reference {found.value!r} is not in {found.key}.")
    payload[found.key] = [value if item is found.value else item for item in held]


def renamed(text: str, overrides: Mapping[str, str]) -> str:
    """Every overridden title inside `text`, replaced."""
    for real, stand_in in overrides.items():
        text = text.replace(real, stand_in)
    return text


def shift_instant(text: str, *, days: int, zone: str) -> str:
    """Move `days` calendar days, same wall time.

    Shifting the UTC instant instead moves the local day by
    one across a daylight-saving change.
    """
    local = instant_from_text(text).astimezone(ZoneInfo(zone))
    moved = local.replace(tzinfo=None) + timedelta(days=days)
    return instant_text(moved.replace(tzinfo=ZoneInfo(zone)).astimezone(UTC))


def shift_dated(
    payload: dict[str, Any], keys: DatedKeys, *, days: int
) -> dict[str, Any]:
    """Copy with every day and instant moved.

    An end is the moved start plus the original elapsed
    time; shifting it alone changes Timed durations
    across a daylight-saving change.
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
        "to commit. Randomizes prices and dates (per-game offset), clears "
        "free-text notes and names and source metadata, and sanitizes audit "
        "timestamps. All "
        "mutation happens inside a rolled-back transaction, so the source database is "
        "never modified.\n\n"
        "Workflow: restore a production dump into a dedicated PostgreSQL database, "
        "set DATABASE_URL to it, run `make migrate`, then run this command for one "
        "explicit User.\n\n"
        "Residual (accepted) traits of the output: cross-model dates are incoherent "
        "(a session can predate its game's purchase, dates may be in the future); row "
        "counts, per-platform split, currency multiset, real ExchangeRate rows and "
        "preserved playtimes remain a distributional fingerprint; the stream head "
        "keeps its real id. Fixture keeps prod "
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
        name_overrides = self._load_overrides(options["name_overrides"])

        with tempfile.TemporaryDirectory() as tempdir:
            dump_path = Path(tempdir) / "dump.yaml"
            with transaction.atomic():
                self._prune_other_libraries(library)
                counts = self._anonymize(
                    all_game_ids,
                    options["scrub_devices"],
                    name_overrides,
                    library_id=library.pk,
                )
                #: Deferred keys hold before the dump.
                connection.check_constraints()
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
        """Hide every other library, inside the rolled-back copy.

        Projections first, raw: RESTRICT and pre_delete are Python's.
        Events before catalog rows: pre_delete guards those too.
        """
        with connection.cursor() as cursor:
            for model in projection_models():
                cursor.execute(
                    f"DELETE FROM {connection.ops.quote_name(model._meta.db_table)}"
                    ' WHERE "library_id" <> %s',
                    [library.pk],
                )
        PurchaseValuation.objects.exclude(library=library).delete()
        FilterPreset.objects.exclude(library=library).delete()
        LibraryEventReference.objects.exclude(library=library).delete()
        LibraryEvent.objects.exclude(library=library).delete()
        LibraryEventStreamHead.objects.exclude(library=library).delete()
        Game.objects.exclude(library=library).delete()
        Platform.objects.filter(library__isnull=False).exclude(library=library).delete()

    def _anonymize(
        self,
        all_game_ids,
        scrub_devices,
        name_overrides,
        *,
        library_id,
    ):
        game_offsets = {
            game_id: timedelta(days=random.randint(-JITTER_DAYS, JITTER_DAYS))
            for game_id in all_game_ids
        }

        if name_overrides:
            retitled = list(Game.objects.filter(name__in=name_overrides).order_by("pk"))
            for game in retitled:
                game.name = name_overrides[game.name]
            Game.objects.bulk_update(retitled, ["name"])
            editions = list(Edition.objects.exclude(name="").order_by("pk"))
            for edition in editions:
                edition.name = renamed(edition.name, name_overrides)
            Edition.objects.bulk_update(editions, ["name"])

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
            **dict(
                HistoricalPlaytime.objects.values_list("pk", "player_game__game_id")
            ),
            **dict(LibraryEntry.objects.values_list("pk", "player_game__game_id")),
            **dict(Purchase.objects.values_list("pk", "entry__player_game__game_id")),
        }

        #: Drawn only for dated devices.
        #: Another draw shifts every later seeded value.
        event_types = DEFAULT_WIRING.event_types
        dated_devices = sorted(
            {
                event.aggregate_id
                for event in LibraryEvent.objects.filter(effective_time__isnull=False)
                if event_types.spec_for(event.event_type).aggregate_type == "device"
            }
        )
        device_offsets = {
            device_id: timedelta(days=random.randint(-JITTER_DAYS, JITTER_DAYS))
            for device_id in dated_devices
        }

        replacements_by_model = self._reassign_uuids()
        event_count, session_count = self._reassign_event_identities(
            game_offsets,
            game_id_by_aggregate,
            replacements_by_model,
            device_offsets=device_offsets,
            library_id=library_id,
        )
        self._reassign_stream_head()

        return {
            "games": len(all_game_ids),
            "entries": LibraryEntry.objects.count(),
            "purchases": Purchase.objects.count(),
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
        #: A key, not a relation.
        for old_id, new_id in replacements_by_model[Device].items():
            UserLibraryPreferences.objects.filter(default_device_id=old_id).update(
                default_device_id=new_id
            )
        return replacements_by_model

    @staticmethod
    def _reassign_event_identities(
        game_offsets,
        game_id_by_aggregate,
        replacements_by_model,
        *,
        device_offsets,
        library_id,
    ):
        """Shift, blank, re-key, re-mint every event.

        Runs after _reassign_uuids: references re-capture at
        final uuids. game_id_by_aggregate is captured before
        that remap, keyed like game_offsets.
        """
        event_types = DEFAULT_WIRING.event_types
        kinds = event_types.reference_kinds
        #: Aggregate order: undated follows dated.
        events = list(LibraryEvent.objects.order_by("aggregate_id", "sequence"))
        #: Keyed and named like its row.
        device_replacements = replacements_by_model.get(Device, {})
        device_names = dict(Device.objects.values_list("pk", "name"))

        def device_keyed(event):
            return event_types.spec_for(event.event_type).aggregate_type == "device"

        last_dated_day: dict[UUID, date] = {}
        sessions_recorded = 0
        #: One key per dispatch; a refund reads it.
        dispatch_keys: dict[tuple[UUID, str], str] = {}
        for event in sorted(events, key=lambda event: event.sequence):
            dispatch_keys.setdefault(
                (event.stream_id, event.idempotency_key), f"sample:{event.sequence}"
            )
        for event in events:
            try:
                library_keyed = event.aggregate_id == library_id
                if library_keyed:
                    offset = timedelta(0)
                elif device_keyed(event):
                    #: A dated fact without its draw raises.
                    offset = (
                        timedelta(0)
                        if event.effective_time is None
                        else device_offsets[event.aggregate_id]
                    )
                else:
                    offset = game_offsets[game_id_by_aggregate[event.aggregate_id]]
                event.effective_time = _shift_effective_time(
                    event.effective_time, offset
                )
                if event.effective_time is not None:
                    last_dated_day[event.aggregate_id] = (
                        event.effective_time.lower_bound
                    )
                #: A removal never precedes its creation.
                day = last_dated_day.get(event.aggregate_id)
                event.recorded_at = FIXED_EPOCH if day is None else _midnight(day)
                payload = shift_dated(
                    event.payload,
                    event_types.dated_keys(event.event_type),
                    days=offset.days,
                )
                if "note" in payload:
                    payload["note"] = ""
                for path in event_types.text_keys(event.event_type):
                    rewrite_path(payload, path, lambda _text: "")
                for path in event_types.amount_keys(event.event_type):
                    rewrite_path(
                        payload, path, lambda _amount: f"{random.uniform(0, 100):.2f}"
                    )
                if "name" in payload:
                    payload["name"] = (
                        device_names[
                            device_replacements.get(
                                event.aggregate_id, event.aggregate_id
                            )
                        ]
                        if device_keyed(event)
                        else ""
                    )
                for found in event_types.references_in(event.event_type, payload):
                    kind = kinds.kind_for(found.value["kind"])
                    replacements = replacements_by_model.get(kind.model, {})
                    old_id = UUID(found.value["id"])
                    replace_reference(
                        payload,
                        found,
                        capture_reference(
                            kind.model._base_manager.get(
                                pk=replacements.get(old_id, old_id)
                            )
                        ),
                    )
                event.payload = payload
                #: Source evidence holds real instants.
                event.source_metadata = {}
                event.idempotency_key = dispatch_keys[
                    (event.stream_id, event.idempotency_key)
                ]
                event.actor = None
                if event.event_type == "library.playersession.created":
                    sessions_recorded += 1
            except (KeyError, ObjectDoesNotExist) as error:
                raise CommandError(
                    f"Event {event.pk} ({event.event_type}) names a row "
                    f"the dump does not hold: {error!r}"
                ) from error
            except CommandError as error:
                raise CommandError(f"Event {event.pk}: {error}") from error
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

        def _group_replacements(rows, key):
            """One new id per distinct group, minted at that group's earliest
            recorded_at, in recorded_at order so two groups born in the same
            millisecond still get distinct sequence numbers."""
            earliest = {}
            for row in rows:
                group = key(row)
                if group not in earliest or row.recorded_at < earliest[group]:
                    earliest[group] = row.recorded_at
            state = {"ms": None, "sequence": None}
            return {
                group: _mint(moment, state)
                for group, moment in sorted(earliest.items(), key=lambda pair: pair[1])
            }

        aggregate_replacements = {
            **_group_replacements(
                [
                    event
                    for event in events
                    if event.aggregate_id != library_id and not device_keyed(event)
                ],
                lambda event: event.aggregate_id,
            ),
            #: The row's replacement; references already name it.
            **{
                event.aggregate_id: device_replacements.get(
                    event.aggregate_id, event.aggregate_id
                )
                for event in events
                if device_keyed(event)
            },
        }
        correlation_replacements = _group_replacements(
            events, lambda event: event.correlation_id
        )

        def reminted_with_aggregate(kind: ReferenceKind[Any]) -> bool:
            """A projection row bar a device."""
            return kind.resolution is Resolution.PROJECTED and kind.model is not Device

        def remapped(kind: ReferenceKind[Any], old_id: UUID, *, subject: str) -> UUID:
            """A projected row takes its aggregate's id.

            A device is re-minted with IDENTITY_MODELS
            and so already holds its new id.
            """
            if reminted_with_aggregate(kind):
                held = aggregate_replacements
                missing = "which no event in this library creates"
            else:
                held = replacements_by_model.get(kind.model, {})
                missing = "which the dump does not hold"
            if old_id not in held:
                raise CommandError(f"{subject} names {kind.name} {old_id}, {missing}.")
            return held[old_id]

        references = list(LibraryEventReference.objects.order_by("pk"))
        for reference in references:
            reference.referenced_id = remapped(
                kinds.kind_for(reference.kind),
                reference.referenced_id,
                subject=f"Reference {reference.pk}",
            )
        LibraryEventReference.objects.bulk_update(references, ["referenced_id"])

        event_moment_by_old_id = {event.pk: event.recorded_at for event in events}
        event_id_replacements = {}
        id_state = {"ms": None, "sequence": None}
        for event in sorted(events, key=lambda event: (event.recorded_at, event.pk)):
            event_id_replacements[event.pk] = _mint(event.recorded_at, id_state)
        #: A join row's id: no aggregate holds it.
        join_id_replacements: dict[UUID, UUID] = {}
        join_id_state: MintState = {"ms": None, "sequence": None}

        def join_id(named: str) -> str:
            old_id = UUID(named)
            if old_id not in join_id_replacements:
                join_id_replacements[old_id] = _mint(FIXED_EPOCH, join_id_state)
            return str(join_id_replacements[old_id])

        def aggregate_id(named: str) -> str:
            old_id = UUID(named)
            if old_id not in aggregate_replacements:
                raise CommandError(
                    f"it names aggregate {old_id}, which no event in this "
                    "library creates."
                )
            return str(aggregate_replacements[old_id])

        for event in events:
            event.aggregate_id = aggregate_replacements.get(
                event.aggregate_id, event.aggregate_id
            )
            event.correlation_id = correlation_replacements[event.correlation_id]
            if event.causation_id is not None:
                event.causation_id = correlation_replacements.get(
                    event.causation_id, event.causation_id
                )
            #: Bare aggregate ids follow the re-minting.
            payload = copy.deepcopy(event.payload)
            try:
                for path in event_types.aggregate_id_keys(event.event_type):
                    rewrite_path(
                        payload,
                        path,
                        join_id if path == JOIN_ID_PATH else aggregate_id,
                    )
                for found in event_types.references_in(event.event_type, payload):
                    kind = kinds.kind_for(found.value["kind"])
                    #: The first pass re-captured the rest.
                    if not reminted_with_aggregate(kind):
                        continue
                    new_id = remapped(kind, UUID(found.value["id"]), subject="it")
                    replace_reference(
                        payload, found, {**found.value, "id": str(new_id)}
                    )
            except CommandError as error:
                raise CommandError(f"Event {event.pk}: {error}") from error
            #: New run ids keep the recorded order.
            if isinstance(payload.get("playthroughs"), list):
                payload["playthroughs"] = sorted_runs(payload["playthroughs"])
            try:
                event_types.validate(event.event_type, payload)
            except PayloadInvalid as error:
                raise CommandError(f"Event {event.pk}: {error}") from error
            event.payload = payload
        #: bulk_update() refuses primary keys; ids swap after.
        LibraryEvent.objects.bulk_update(
            events, ["aggregate_id", "correlation_id", "causation_id", "payload"]
        )
        for old_id, new_id in event_id_replacements.items():
            LibraryEvent.objects.filter(pk=old_id).update(id=new_id)

        reference_id_state = {"ms": None, "sequence": None}
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

    @classmethod
    def _reassign_stream_head(cls):
        """Mint the head at its first event."""
        head = LibraryEventStreamHead.objects.first()
        if head is None:
            return
        first = LibraryEvent.objects.aggregate(first=Min("recorded_at"))["first"]
        new_id = _mint(first or FIXED_EPOCH, {"ms": None, "sequence": None})
        LibraryEventStreamHead.objects.filter(pk=head.pk).update(id=new_id)
        cls._remap_referrers(LibraryEventStreamHead, {head.pk: new_id})

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
        """Assign uuids encoding `created_at`, or the epoch, in order.

        Entropy comes from the seeded RNG rather than `secrets`, which is what
        keeps the output byte-identical for a given --seed.
        """
        identity = cls._identity_field_name(model)
        dated = any(field.name == "created_at" for field in model._meta.fields)
        ordering = ("created_at", "pk") if dated else ("pk",)
        rows = list(model._base_manager.order_by(*ordering))
        replacements = {}
        state: MintState = {"ms": None, "sequence": None}
        for row in rows:
            moment = row.created_at if dated else FIXED_EPOCH
            replacements[getattr(row, identity)] = _mint(moment, state)
        # One UPDATE per row rather than bulk_update: the latter refuses a
        # primary-key field outright, which is what `identity` is for a promoted
        # model. A queryset update writes either.
        for original, replacement in replacements.items():
            model._base_manager.filter(**{identity: original}).update(
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
        drops relations whose `related_name` ends in "+".

        Many-to-many relations are walked too, via their through model's own
        foreign key. Whether a relation needs remapping is decided by what it
        targets, never by its kind: an auto-created through references the
        target's primary key, so such a relation is inert while the identity
        is a secondary column and live once it is the primary key.

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
            for key in GENERATED_FIELDS.get(item.get("model", ""), frozenset()):
                fields.pop(key, None)
            if item.get("model") == "games.libraryevent":
                if fields.get("effective_time") == "":
                    fields.pop("effective_time", None)
                #: Library-keyed aggregate: the owner marker.
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
