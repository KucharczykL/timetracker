from __future__ import annotations

import gzip
from io import StringIO
from pathlib import Path

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
            platform_ids = self._load_platforms(records, user.library)
            self._load_exchange_rates(records)
            loadable = self._prepare_private_records(
                records,
                user.library,
                platform_ids,
            )
            self._reject_primary_key_collisions(loadable)
            try:
                for deserialized in serializers.deserialize(
                    "yaml",
                    StringIO(yaml.safe_dump(loadable, sort_keys=False)),
                ):
                    deserialized.save()
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
        for record in records:
            if not isinstance(record, dict) or not isinstance(
                record.get("fields"), dict
            ):
                raise CommandError("Every sample fixture entry must contain fields.")
            model = record.get("model")
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

    @staticmethod
    def _load_platforms(records, library):
        platform_ids = {}
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
            platform_ids[record.get("pk")] = platform.pk
        return platform_ids

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
    def _prepare_private_records(records, library, platform_ids):
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
                platform_id = fields.get("platform")
                if platform_id is not None:
                    if platform_id not in platform_ids:
                        raise CommandError(
                            f"Sample {model} references unknown Platform {platform_id}."
                        )
                    fields["platform"] = platform_ids[platform_id]
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
