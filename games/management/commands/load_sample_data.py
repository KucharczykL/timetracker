from __future__ import annotations

import gzip
from io import StringIO
from pathlib import Path
from typing import NamedTuple

import yaml
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.base import DeserializationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from games.conversion import _request_conversion_for_locked_state
from games.models import (
    Device,
    ExchangeRate,
    FilterPreset,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
    Purchase,
    PurchaseConversionState,
    Session,
)

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "sample.yaml.gz"
TARGET_LIBRARY_MARKER = "__target_library__"

PRIVATE_MODELS = {
    "games.device": Device,
    "games.game": Game,
    "games.purchase": Purchase,
    "games.filterpreset": FilterPreset,
}
LOADABLE_MODELS = {
    **PRIVATE_MODELS,
    "games.session": Session,
    "games.playevent": PlayEvent,
    "games.gamestatuschange": GameStatusChange,
}


class FixtureRelationship(NamedTuple):
    """One FK/M2M reference field on a fixture record.

    `reference_field` names which field of the *target* record the reference
    value names — the fixture-validation equivalent of the FK's `to_field`.
    Defaults to "pk" for an ordinary primary-key relation. Name another field
    only when the database FK deliberately targets a secondary identity.
    """

    field: str
    target_model: str
    many: bool
    required: bool
    reference_field: str = "pk"


FIXTURE_RELATIONSHIPS: dict[str, tuple[FixtureRelationship, ...]] = {
    "games.game": (
        FixtureRelationship(
            "platform", "games.platform", False, False, reference_field="pk"
        ),
    ),
    "games.purchase": (
        FixtureRelationship(
            "platform", "games.platform", False, False, reference_field="pk"
        ),
        FixtureRelationship(
            "related_game", "games.game", False, False, reference_field="pk"
        ),
        FixtureRelationship("games", "games.game", True, False),
    ),
    "games.session": (
        FixtureRelationship("game", "games.game", False, True, reference_field="pk"),
        FixtureRelationship("device", "games.device", False, False),
    ),
    "games.playevent": (
        FixtureRelationship("game", "games.game", False, True, reference_field="pk"),
    ),
    "games.gamestatuschange": (
        FixtureRelationship("game", "games.game", False, True, reference_field="pk"),
    ),
}


class Command(BaseCommand):
    help = (
        "Load the portable sample fixture for one existing User, assigning every "
        "private row to that User's library."
    )

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Existing owner username.")

    def handle(self, *args, **options):
        username = options["user"]
        user_model = get_user_model()
        try:
            user = user_model.objects.select_related("library").get(username=username)
        except user_model.DoesNotExist as error:
            raise CommandError(f"User {username!r} does not exist.") from error

        records = self._read_fixture()
        self._validate_records(records)

        with transaction.atomic():
            state = PurchaseConversionState.objects.select_for_update().get(
                library=user.library
            )
            platform_uuids = self._load_platforms(records, user.library)
            self._load_exchange_rates(records)
            loadable = self._prepare_private_records(
                records,
                user.library,
                platform_uuids,
            )
            self._reject_primary_key_collisions(loadable)
            try:
                for deserialized in serializers.deserialize(
                    "yaml",
                    StringIO(yaml.safe_dump(loadable, sort_keys=False)),
                ):
                    deserialized.save(force_insert=True)
            except (DeserializationError, IntegrityError, ValueError) as error:
                raise CommandError(
                    f"Sample fixture could not be loaded: {error}"
                ) from error

            purchases = Purchase.objects.for_library(user.library)
            cache_mismatch = purchases.filter(
                Q(converted_price__isnull=True)
                | Q(needs_price_update=True)
                | ~Q(converted_currency__iexact=state.requested_currency)
            ).exists()
            if cache_mismatch or state.requested_version != state.published_version:
                _request_conversion_for_locked_state(
                    state,
                    state.requested_currency,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(loadable)} sample object(s) for User {username!r} "
                f"into library {user.library.pk}."
            )
        )

    @staticmethod
    def _read_fixture():
        try:
            if FIXTURE_PATH.suffix == ".gz":
                with gzip.open(FIXTURE_PATH, "rt") as fixture:
                    records = yaml.safe_load(fixture)
            else:
                with FIXTURE_PATH.open() as fixture:
                    records = yaml.safe_load(fixture)
        except (OSError, yaml.YAMLError) as error:
            raise CommandError(
                f"Sample fixture is unreadable: {FIXTURE_PATH}"
            ) from error
        return records or []

    @staticmethod
    def _validate_records(records):
        if not isinstance(records, list):
            raise CommandError("Sample fixture root must be a list.")
        supported = set(LOADABLE_MODELS) | {"games.platform", "games.exchangerate"}
        record_keys = set()

        # Which non-pk fields each model needs indexed, derived from every
        # relationship's reference_field, so a relation deliberately targeting
        # a secondary identity needs no further validation change here.
        reference_fields_needed: dict[str, set[str]] = {}
        for relationships in FIXTURE_RELATIONSHIPS.values():
            for relationship in relationships:
                if relationship.reference_field == "pk":
                    continue
                reference_fields_needed.setdefault(
                    relationship.target_model, set()
                ).add(relationship.reference_field)

        # (model, reference_field) -> set of reference-field values present
        # among that model's fixture records, for non-pk reference fields.
        reference_index: dict[tuple[str, str], set[str]] = {}

        for record in records:
            if not isinstance(record, dict) or not isinstance(
                record.get("fields"), dict
            ):
                raise CommandError("Every sample fixture entry must contain fields.")
            model = record.get("model")
            primary_key = record.get("pk")
            if primary_key is None:
                raise CommandError(f"Sample {model} is missing a primary key.")
            record_key = (model, str(primary_key))
            if record_key in record_keys:
                raise CommandError(
                    f"Sample fixture has duplicate {model} primary key {primary_key}."
                )
            record_keys.add(record_key)
            fields = record["fields"]
            if model not in supported:
                raise CommandError(f"Unsupported model in sample fixture: {model!r}.")
            if (
                model in PRIVATE_MODELS
                and fields.get("library") != TARGET_LIBRARY_MARKER
            ):
                raise CommandError(
                    f"Sample {model} is missing the portable owner marker."
                )
            if model == "games.platform" and fields.get("library") not in (
                None,
                TARGET_LIBRARY_MARKER,
            ):
                raise CommandError("Sample Platform has an invalid owner marker.")

            for reference_field in reference_fields_needed.get(model, ()):
                value = fields.get(reference_field)
                if value is not None:
                    reference_index.setdefault((model, reference_field), set()).add(
                        str(value)
                    )

        for record in records:
            model = record["model"]
            fields = record["fields"]
            for relationship in FIXTURE_RELATIONSHIPS.get(model, ()):
                value = fields.get(relationship.field)
                if value is None:
                    if relationship.required:
                        raise CommandError(
                            f"Sample {model} {record['pk']} is missing required "
                            f"{relationship.target_model.rsplit('.', 1)[1].title()} "
                            f"reference {relationship.field}."
                        )
                    continue
                if relationship.many:
                    if not isinstance(value, list):
                        raise CommandError(
                            f"Sample {model} {record['pk']} field "
                            f"{relationship.field} must be a list."
                        )
                    references = value
                else:
                    references = [value]
                for reference in references:
                    if relationship.reference_field == "pk":
                        found = (
                            relationship.target_model,
                            str(reference),
                        ) in record_keys
                    else:
                        found = str(reference) in reference_index.get(
                            (relationship.target_model, relationship.reference_field),
                            set(),
                        )
                    if not found:
                        target_label = relationship.target_model.rsplit(".", 1)[
                            1
                        ].title()
                        raise CommandError(
                            f"Sample {model} {record['pk']} references {target_label} "
                            f"{reference}, which is not included in the fixture."
                        )

    @staticmethod
    def _load_platforms(records, library):
        """Create or reuse each fixture platform, returning fixture id → real id.

        Both platform references in the fixture name the target's primary key,
        and the real row's is never the fixture's on either path: a reused row
        already had its own, and a created one mints a fresh one from
        `UUIDv7Field`'s default. Adopting the fixture's instead is not an
        option — `_reject_primary_key_collisions` guards against exactly that
        collision, and the reuse path could not honor it anyway. So the
        translation here is load-bearing: without it every game and purchase
        would dangle.

        Values are strings because the prepared records are re-serialized with
        `yaml.safe_dump` before deserialization, which cannot represent a UUID.
        """
        platform_uuids = {}
        for record in records:
            if record["model"] != "games.platform":
                continue
            fields = record["fields"]
            owner = None if fields.get("library") is None else library
            platform = Platform.objects.filter(
                library=owner,
                name=fields["name"],
                group=fields.get("group", ""),
            ).first()
            if platform is None:
                try:
                    platform = Platform.objects.create(
                        library=owner,
                        name=fields["name"],
                        group=fields.get("group", ""),
                        icon=fields.get("icon", ""),
                    )
                except (IntegrityError, ValidationError) as error:
                    raise CommandError(
                        "Sample Platform has no reusable exact identity: "
                        f"{fields['name']!r} / {fields.get('group', '')!r}."
                    ) from error
            # A fixture platform carrying no pk is legal input — validation
            # indexes reference fields with .get() and only errors at the
            # referencing record — so it simply maps nothing.
            fixture_identity = record.get("pk")
            if fixture_identity is not None:
                platform_uuids[str(fixture_identity)] = str(platform.pk)
        return platform_uuids

    @staticmethod
    def _load_exchange_rates(records):
        for record in records:
            if record["model"] != "games.exchangerate":
                continue
            fields = record["fields"]
            ExchangeRate.objects.update_or_create(
                currency_from=fields["currency_from"],
                currency_to=fields["currency_to"],
                year=fields["year"],
                defaults={"rate": fields["rate"]},
            )

    @staticmethod
    def _prepare_private_records(records, library, platform_uuids):
        prepared = []
        for record in records:
            model = record["model"]
            if model in {"games.platform", "games.exchangerate"}:
                continue
            copied = {**record, "fields": dict(record["fields"])}
            fields = copied["fields"]
            if model in PRIVATE_MODELS:
                fields["library"] = str(library.pk)
            if model in {"games.game", "games.purchase"}:
                platform_reference = fields.get("platform")
                if platform_reference is not None:
                    if str(platform_reference) not in platform_uuids:
                        raise CommandError(
                            f"Sample {model} references unknown Platform "
                            f"{platform_reference}."
                        )
                    fields["platform"] = platform_uuids[str(platform_reference)]
            prepared.append(copied)
        return prepared

    @staticmethod
    def _reject_primary_key_collisions(records):
        for record in records:
            primary_key = record.get("pk")
            model = LOADABLE_MODELS[record["model"]]
            if (
                primary_key is not None
                and model.objects.filter(pk=primary_key).exists()
            ):
                raise CommandError(
                    f"Sample {record['model']} primary key {primary_key} already exists; "
                    "nothing was loaded."
                )
