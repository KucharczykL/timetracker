from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

if TYPE_CHECKING:
    from games.models import Edition, ExternalReference, Game, Platform, Release

    type CatalogTarget = Game | Edition | Release | Platform
else:
    type CatalogTarget = object

WIKIDATA_KEY_PATTERN = re.compile(r"Q[1-9][0-9]*")


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    """What a provider states, and how it reads.

    The one entry a provider needs. A form field, its label, its
    help text and its link all come from here, thus registering a
    policy is the whole UI cost of a provider.
    """

    normalize_key: Callable[[str], str]
    url_template: str
    label: str
    hint: str


def _normalize_wikidata_key(provider_key: str) -> str:
    key = provider_key.strip().upper()
    if not WIKIDATA_KEY_PATTERN.fullmatch(key):
        raise ValidationError(
            {"provider_key": "Enter a Wikidata entity ID such as Q123."}
        )
    return key


PROVIDER_POLICIES = {
    "wikidata": ProviderPolicy(
        normalize_key=_normalize_wikidata_key,
        url_template="https://www.wikidata.org/wiki/{provider_key}",
        label="Wikidata",
        hint="An entity ID such as Q123.",
    ),
}


def provider_labels() -> dict[str, str]:
    """Every registered provider, under the words a person reads."""
    return {provider: policy.label for provider, policy in PROVIDER_POLICIES.items()}


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().casefold()
    if normalized not in PROVIDER_POLICIES:
        raise ValidationError({"provider": "Unsupported external-reference provider."})
    return normalized


def normalize_provider_key(*, provider: str, provider_key: str) -> tuple[str, str]:
    provider = normalize_provider(provider)
    return provider, PROVIDER_POLICIES[provider].normalize_key(provider_key)


def external_reference_url(
    *, provider: str, entity_kind: str, provider_key: str
) -> str:
    if entity_kind not in {"game", "edition", "release", "platform"}:
        raise ValidationError({"entity_kind": "Unsupported catalog entity kind."})
    provider, key = normalize_provider_key(provider=provider, provider_key=provider_key)
    policy = PROVIDER_POLICIES[provider]
    return policy.url_template.format(
        entity_kind=quote(entity_kind, safe=""),
        provider_key=quote(key, safe=""),
    )


def _target_metadata(target: CatalogTarget) -> tuple[str, str]:
    from games.models import Edition, Game, Platform, Release

    target_metadata = {
        Game: ("game", "game"),
        Edition: ("edition", "edition"),
        Release: ("release", "release"),
        Platform: ("platform", "platform"),
    }
    try:
        return target_metadata[type(target)]
    except KeyError as error:
        raise ValidationError({"target": "Unsupported catalog target."}) from error


def save_external_reference(
    *, provider: str, provider_key: str, target: CatalogTarget
) -> ExternalReference:
    """Persist one canonical provider tuple without allowing target reassignment."""
    from games.models import ExternalReference

    provider, provider_key = normalize_provider_key(
        provider=provider, provider_key=provider_key
    )
    entity_kind, target_field = _target_metadata(target)
    tuple_filters = {
        "provider": provider,
        "entity_kind": entity_kind,
        "provider_key": provider_key,
    }

    with transaction.atomic():
        reference = (
            ExternalReference.objects.select_for_update()
            .filter(**tuple_filters)
            .first()
        )
        if reference is None:
            try:
                with transaction.atomic():
                    return ExternalReference.objects.create(
                        **tuple_filters, **{target_field: target}
                    )
            except IntegrityError:
                reference = (
                    ExternalReference.objects.select_for_update()
                    .filter(**tuple_filters)
                    .get()
                )

        if reference.target_uuid == target.pk:
            return reference
        raise ValidationError(
            {
                "provider_key": (
                    "This external reference already maps to another catalog target."
                )
            }
        )


def resolve_external_reference(
    *, provider: str, entity_kind: str, provider_key: str
) -> UUID | None:
    """Resolve one canonical provider tuple to its target UUID."""
    from games.models import ExternalReference

    target_id_fields = {
        "game": "game_id",
        "edition": "edition_id",
        "release": "release_id",
        "platform": "platform_id",
    }
    try:
        target_id_field = target_id_fields[entity_kind]
    except KeyError as error:
        raise ValidationError(
            {"entity_kind": "Unsupported catalog entity kind."}
        ) from error

    provider, provider_key = normalize_provider_key(
        provider=provider, provider_key=provider_key
    )
    return (
        ExternalReference.objects.filter(
            provider=provider,
            entity_kind=entity_kind,
            provider_key=provider_key,
        )
        .values_list(target_id_field, flat=True)
        .first()
    )


def sync_game_wikidata(*, game: Game) -> ExternalReference | None:
    """Synchronize the temporary Game.wikidata compatibility field to its reference."""
    from games.models import ExternalReference, Game

    legacy_key = game.wikidata.strip()
    with transaction.atomic():
        persisted_game = Game.objects.select_for_update().get(pk=game.pk)
        references = list(
            ExternalReference.objects.select_for_update().filter(
                provider="wikidata", entity_kind="game", game_id=game.pk
            )
        )
        if not legacy_key:
            for reference in references:
                reference.delete()
            persisted_game.wikidata = ""
            persisted_game.save(update_fields=("wikidata",))
            game.wikidata = ""
            return None

        _, canonical_key = normalize_provider_key(
            provider="wikidata", provider_key=legacy_key
        )
        for reference in references:
            if reference.provider_key != canonical_key:
                reference.delete()
        synced = save_external_reference(
            provider="wikidata", provider_key=canonical_key, target=persisted_game
        )
        persisted_game.wikidata = canonical_key
        persisted_game.save(update_fields=("wikidata",))
        game.wikidata = canonical_key
        return synced
