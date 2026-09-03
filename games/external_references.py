from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import quote
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.timezone import now

if TYPE_CHECKING:
    from games.models import (
        Edition,
        ExternalReference,
        Game,
        Platform,
        Release,
        UserLibrary,
    )

    type CatalogTarget = Game | Edition | Release | Platform
else:
    type CatalogTarget = object

logger = logging.getLogger("games")

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


#: A shared row is read-only for everyone, and what sharing means
#: is unsettled until the IGDB wave (#783, #784, #785) lands.
SHARED_TARGET = "A shared record's references cannot be changed here."
OTHER_LIBRARY_TARGET = "This record belongs to another library."
REMOVED_TARGET = "This record was removed. Put it back before you change it."
KEY_TAKEN = "Another record already states this identifier."


class ReferencesRefused(ValidationError):
    """A refusal, and the provider whose box caused it."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


def _owner_and_mark(target: CatalogTarget) -> tuple[UUID | None, bool]:
    """Which library holds the row, and whether it was removed.

    An Edition and a Release read their ancestors' marks as well as
    their own, the way `for_library()` does: a removed Game hides
    both, so neither may be written under it.
    """
    from games.models import Edition, Game, Platform, Release

    if isinstance(target, Game | Platform):
        return target.library_id, target.removed_at is not None
    if isinstance(target, Edition):
        game = target.game
        return game.library_id, (
            target.removed_at is not None or game.removed_at is not None
        )
    if isinstance(target, Release):
        edition = target.edition
        game = edition.game
        return game.library_id, (
            target.removed_at is not None
            or edition.removed_at is not None
            or game.removed_at is not None
        )
    raise ValidationError({"target": "Unsupported catalog target."})


def _refuse_an_unwritable_target(target: CatalogTarget, library: UserLibrary) -> None:
    """A shared, foreign or removed record states nothing here."""
    owner, removed = _owner_and_mark(target)
    if owner is None:
        raise ReferencesRefused(SHARED_TARGET)
    if owner != library.pk:
        raise ReferencesRefused(OTHER_LIBRARY_TARGET)
    if removed:
        raise ReferencesRefused(REMOVED_TARGET)


def _normalized_or_refused(provider: str, raw: str) -> str:
    """A blank box states no reference; anything else normalizes."""
    if not raw.strip():
        return ""
    try:
        _, provider_key = normalize_provider_key(provider=provider, provider_key=raw)
    except ValidationError as refusal:
        raise ReferencesRefused(
            refusal.messages[0], provider=normalize_provider(provider)
        ) from refusal
    return provider_key


def _refuse_a_taken_key(
    wanted: Mapping[str, str],
    held: Mapping[str, ExternalReference],
    entity_kind: str,
) -> None:
    """A key a live row of this kind already holds.

    No pre-check wins a race; the conditional constraint answers
    the one this loses, and `games/catalog_submit.py` reads the
    name the database gave.
    """
    from games.models import ExternalReference

    for provider, provider_key in wanted.items():
        if not provider_key:
            continue
        incumbent = held.get(provider)
        clash = ExternalReference.objects.filter(
            provider=provider,
            entity_kind=entity_kind,
            provider_key=provider_key,
            removed_at__isnull=True,
        )
        if incumbent is not None:
            clash = clash.exclude(pk=incumbent.pk)
        if clash.exists():
            raise ReferencesRefused(KEY_TAKEN, provider=provider)


def _state_one(
    provider: str,
    provider_key: str,
    incumbent: ExternalReference | None,
    target: CatalogTarget,
    entity_kind: str,
    column: str,
) -> None:
    """One provider's box, as one write."""
    from games.models import ExternalReference

    if incumbent is not None:
        if incumbent.provider_key == provider_key:
            return
        ExternalReference.objects.filter(pk=incumbent.pk).update(removed_at=now())
    if not provider_key:
        return
    ExternalReference.objects.create(
        provider=provider,
        entity_kind=entity_kind,
        provider_key=provider_key,
        **{column: target},
    )


def state_external_references(
    *,
    target: CatalogTarget,
    library: UserLibrary,
    keys: Mapping[str, str],
) -> None:
    """One record's whole desired set, for the providers named.

    A provider the caller does not name is left alone: a writer
    that knows one provider must not take another's row. Removal
    is a mark. Every refusal is read before anything is written,
    and each carries the provider whose box caused it.
    """
    from games.models import ExternalReference

    entity_kind, column = _target_metadata(target)
    wanted = {
        normalize_provider(provider): _normalized_or_refused(provider, raw)
        for provider, raw in keys.items()
    }
    with transaction.atomic():
        _refuse_an_unwritable_target(target, library)
        held = {
            reference.provider: reference
            for reference in ExternalReference.objects.select_for_update()
            .filter(removed_at__isnull=True, **{f"{column}_id": target.pk})
            .filter(provider__in=wanted)
        }
        _refuse_a_taken_key(wanted, held, entity_kind)
        for provider, provider_key in wanted.items():
            _state_one(
                provider,
                provider_key,
                held.get(provider),
                target,
                entity_kind,
                column,
            )


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

    #: Only a live row holds the slot: the constraint now reads the
    #: mark, thus a removed row must not answer this lookup either.
    live = {**tuple_filters, "removed_at__isnull": True}

    with transaction.atomic():
        reference = ExternalReference.objects.select_for_update().filter(**live).first()
        if reference is None:
            try:
                with transaction.atomic():
                    return ExternalReference.objects.create(
                        **tuple_filters, **{target_field: target}
                    )
            except IntegrityError:
                reference = (
                    ExternalReference.objects.select_for_update().filter(**live).get()
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


def mirror_game_wikidata(game: Game) -> None:
    """Write `Game.wikidata` from the reference that states it.

    The reference is what a person states; the column is what
    filters, sorting, the games list, the API and the sample
    fixture still read. An UPDATE rather than a save(), like
    `mirror_legacy_columns()`, so the mirror revalidates nothing
    and fires no signal. #889 takes the column.
    """
    from games.models import ExternalReference, Game

    live = (
        ExternalReference.objects.filter(
            provider="wikidata",
            entity_kind="game",
            game_id=game.pk,
            removed_at__isnull=True,
        )
        .values_list("provider_key", flat=True)
        .first()
    ) or ""
    if game.wikidata == live:
        return
    Game.objects.filter(pk=game.pk).update(wikidata=live)
    game.wikidata = live


class BackfilledReferences(NamedTuple):
    """What a fixture load's backfill wrote, and why it left the rest.

    Two causes, counted apart: a column another record's key has
    already taken, and a column that is not an entity ID at all.
    One number for both would send an operator hunting a conflict
    that is not there.
    """

    written: int
    taken: int
    malformed: int


def backfill_wikidata_references(library: UserLibrary) -> BackfilledReferences:
    """The reference a loaded Game's column still stands for.

    Migration 0022 writes one for every Game a migrated database
    holds. A fixture load is the other source of a Game whose
    `wikidata` column names a key no reference states, and the
    column is the mirror now: an edit that read no reference
    would write the column empty. A key another live row already
    holds is left alone and counted, because two libraries may
    load the same fixture and #654 and #785 own that
    reconciliation.

    A removed Game keeps its column and is left alone: nothing may
    state a reference under a row a person has taken out, and the
    refusal would abort the whole load.
    """
    from games.models import ExternalReference, Game

    stated = set(
        ExternalReference.objects.filter(
            provider="wikidata", entity_kind="game", removed_at__isnull=True
        ).values_list("provider_key", flat=True)
    )
    written = taken = malformed = 0
    unreferenced = (
        Game.objects.filter(library=library, removed_at__isnull=True)
        .exclude(wikidata="")
        .exclude(
            pk__in=ExternalReference.objects.filter(
                provider="wikidata", entity_kind="game", removed_at__isnull=True
            ).values("game_id")
        )
    )
    for game in unreferenced:
        try:
            provider, key = normalize_provider_key(
                provider="wikidata", provider_key=game.wikidata
            )
        except ValidationError as refusal:
            logger.warning(
                "Game %s keeps the Wikidata column %r: %s",
                game.pk,
                game.wikidata,
                refusal.messages[0],
            )
            malformed += 1
            continue
        if key in stated:
            logger.warning(
                "Game %s keeps the Wikidata column %r: another record states it.",
                game.pk,
                game.wikidata,
            )
            taken += 1
            continue
        state_external_references(target=game, library=library, keys={provider: key})
        stated.add(key)
        written += 1
    return BackfilledReferences(written, taken, malformed)
