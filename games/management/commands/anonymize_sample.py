import gzip
import random
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from games.models import Device, Game, PlayEvent, Platform, Purchase, Session

# DB-computed columns: the serializer emits them, loaddata discards them.
# Stripped to keep the fixture clean.
GENERATED_FIELDS = frozenset(
    ["price_per_game", "duration_calculated", "duration_total", "days_to_finish"]
)

# Dumped models, dependencies first (Game before its FK referrers).
# Omitted: GameStatusChange (regenerated), FilterPreset (User FK).
DUMP_LABELS = [
    "games.Platform",
    "games.Device",
    "games.Game",
    "games.Purchase",
    "games.Session",
    "games.PlayEvent",
    "games.ExchangeRate",
]

# Deterministic stand-in for audit timestamps with no natural date to derive from.
FIXED_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)

MAX_GAMES_PER_PURCHASE = 10
JITTER_DAYS = 365
CONVERSION_RATE = 23.0

# Gitignored map of real game name -> replacement, applied at generation so
# sensitive titles never enter the committed fixture. Absent = no-op.
DEFAULT_NAME_OVERRIDES = (
    Path(__file__).resolve().parents[2] / "fixtures" / "name_overrides.yaml"
)


def _midnight(date_value):
    return datetime(
        date_value.year, date_value.month, date_value.day, tzinfo=timezone.utc
    )


class Command(BaseCommand):
    help = (
        "Regenerate games/fixtures/sample.yaml.gz from the currently-loaded database "
        "(a production copy), anonymizing the sensitive parts so the result is safe "
        "to commit. Randomizes prices, game<->purchase links, and dates (per-game "
        "offset), clears free-text notes, and sanitizes audit timestamps. All "
        "mutation happens inside a rolled-back transaction, so the source database is "
        "never modified.\n\n"
        "Workflow: copy a prod dump into $DATA_DIR/db.sqlite3, run `make migrate`, "
        "then run this command.\n\n"
        "Residual (accepted) traits of the output: cross-model dates are incoherent "
        "(a session can predate its game's purchase, dates may be in the future); row "
        "counts, per-platform split, currency multiset, real ExchangeRate rows and "
        "preserved playtimes remain a distributional fingerprint. Fixture keeps prod "
        "pks, so loading it over a non-empty dev DB overwrites same-pk rows."
    )

    def add_arguments(self, parser):
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
            help="Replace device names with generic 'Device {pk}' labels.",
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

        all_game_ids = list(Game.objects.order_by("pk").values_list("pk", flat=True))
        if not all_game_ids and Purchase.objects.exists():
            raise CommandError("Purchases exist but no games to reassign them to.")

        name_overrides = self._load_overrides(options["name_overrides"])

        with tempfile.TemporaryDirectory() as tempdir:
            dump_path = Path(tempdir) / "dump.yaml"
            with transaction.atomic():
                counts = self._anonymize(
                    all_game_ids, options["scrub_devices"], name_overrides
                )
                call_command(
                    "dumpdata",
                    *DUMP_LABELS,
                    format="yaml",
                    indent=2,
                    output=str(dump_path),
                )
                transaction.set_rollback(True)
            self._write_fixture(dump_path, output_path)

        self.stdout.write(
            self.style.SUCCESS(
                "Wrote anonymized fixture to "
                f"{output_path}: "
                + ", ".join(f"{count} {name}" for name, count in counts.items())
            )
        )

    def _anonymize(self, all_game_ids, scrub_devices, name_overrides):
        game_offsets = {
            game_id: timedelta(days=random.randint(-JITTER_DAYS, JITTER_DAYS))
            for game_id in all_game_ids
        }

        sessions = list(Session.objects.order_by("pk"))
        for session in sessions:
            if session.game_id is not None:
                offset = game_offsets[session.game_id]
            else:
                offset = timedelta(days=random.randint(-JITTER_DAYS, JITTER_DAYS))
            session.timestamp_start += offset
            if session.timestamp_end is not None:
                session.timestamp_end += offset
            session.note = ""
            session.created_at = session.timestamp_start
            session.modified_at = session.timestamp_start
        Session.objects.bulk_update(
            sessions,
            ["timestamp_start", "timestamp_end", "note", "created_at", "modified_at"],
        )

        playevents = list(PlayEvent.objects.order_by("pk"))
        for event in playevents:
            offset = game_offsets[event.game_id]
            if event.started is not None:
                event.started += offset
            if event.ended is not None:
                event.ended += offset
            event.note = ""
            event.created_at = (
                _midnight(event.started) if event.started is not None else FIXED_EPOCH
            )
            event.updated_at = event.created_at
        PlayEvent.objects.bulk_update(
            playevents, ["started", "ended", "note", "created_at", "updated_at"]
        )

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
                purchase.related_game_id = random.choice(all_game_ids)
            count = random.randint(1, min(MAX_GAMES_PER_PURCHASE, len(all_game_ids)))
            chosen = random.sample(all_game_ids, count)
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
            for device in devices:
                device.name = f"Device {device.pk}"
            Device.objects.bulk_update(devices, ["name"])

        return {
            "games": len(all_game_ids),
            "purchases": len(purchases),
            "sessions": len(sessions),
            "playevents": len(playevents),
        }

    def _load_overrides(self, path):
        if not path or not path.exists():
            return {}
        with path.open() as stream:
            mapping = yaml.safe_load(stream) or {}
        return {str(old): str(new) for old, new in mapping.items()}

    def _write_fixture(self, dump_path, output_path):
        with dump_path.open() as stream:
            objects = yaml.safe_load(stream) or []
        for item in objects:
            for key in GENERATED_FIELDS:
                item.get("fields", {}).pop(key, None)
        payload = yaml.safe_dump(
            objects, sort_keys=True, default_flow_style=False
        ).encode()
        # mtime=0 and no embedded filename keep the gzip output byte-identical
        # across runs, so a fixed --seed yields a stable git blob.
        output_path.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
