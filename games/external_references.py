from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NamedTuple
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

#: Four rows may state an external reference.
type CatalogTarget = Game | Edition | Release | Platform

#: A casefolded, stripped key of `PROVIDER_POLICIES`.
type ProviderName = str

#: One provider's own form of a key.
type ProviderKey = str

logger = logging.getLogger("games")

WIKIDATA_KEY_PATTERN = re.compile(r"Q[1-9][0-9]*")

#: The one scheme a template may carry.
#:
#: The node layer escapes the characters of an href and never reads
#: its scheme, so `http` or `javascript` would go out as written.
TRUSTED_SCHEME = "https://"

#: What a template interpolates for one entity.
KEY_PLACEHOLDER = "{provider_key}"


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    """One provider's key rule, link, label, hint."""

    normalize_key: Callable[[str], ProviderKey]
    url_template: str
    label: str
    hint: str

    def __post_init__(self) -> None:
        """Refuse a template that states no link."""
        if not self.url_template.startswith(TRUSTED_SCHEME):
            raise ValueError(
                f"A provider's url_template must start with {TRUSTED_SCHEME!r}: "
                f"{self.url_template!r}"
            )
        if KEY_PLACEHOLDER not in self.url_template:
            raise ValueError(
                f"A provider's url_template must interpolate {KEY_PLACEHOLDER}: "
                f"{self.url_template!r}"
            )


def _normalize_wikidata_key(provider_key: str) -> ProviderKey:
    key = provider_key.strip().upper()
    if not WIKIDATA_KEY_PATTERN.fullmatch(key):
        raise ValidationError(
            {"provider_key": "Enter a Wikidata entity ID such as Q123."}
        )
    return key


PROVIDER_POLICIES: Final[Mapping[ProviderName, ProviderPolicy]] = {
    "wikidata": ProviderPolicy(
        normalize_key=_normalize_wikidata_key,
        url_template="https://www.wikidata.org/wiki/{provider_key}",
        label="Wikidata",
        hint="An entity ID such as Q123.",
    ),
}


def _refuse_a_key_nothing_can_reach(policies: Mapping[str, ProviderPolicy]) -> None:
    """A miscased registry key names no policy."""
    miscased = sorted(name for name in policies if name != name.casefold())
    if miscased:
        raise ValueError(f"A provider's registry key must be casefolded: {miscased}")


_refuse_a_key_nothing_can_reach(PROVIDER_POLICIES)


def normalize_provider(provider: str) -> ProviderName:
    normalized = provider.strip().casefold()
    if normalized not in PROVIDER_POLICIES:
        raise ValidationError({"provider": "Unsupported external-reference provider."})
    return normalized


class NormalizedReference(NamedTuple):
    """One provider and one key, as stored."""

    provider: ProviderName
    provider_key: ProviderKey


def normalize_provider_key(*, provider: str, provider_key: str) -> NormalizedReference:
    provider = normalize_provider(provider)
    return NormalizedReference(
        provider, PROVIDER_POLICIES[provider].normalize_key(provider_key)
    )


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


def external_reference_url_or_none(
    *, provider: str, entity_kind: str, provider_key: str
) -> str | None:
    """None where the key states no link.

    A mirror column carries no check constraint, thus a value the
    pattern rejects reaches a reader. It must not take the page.
    """
    try:
        return external_reference_url(
            provider=provider, entity_kind=entity_kind, provider_key=provider_key
        )
    except ValidationError:
        return None


class TargetMetadata(NamedTuple):
    """The stored word, and its column."""

    entity_kind: str
    column: str


def _target_metadata(target: CatalogTarget) -> TargetMetadata:
    from games.models import Edition, Game, Platform, Release

    target_metadata = {
        Game: TargetMetadata("game", "game"),
        Edition: TargetMetadata("edition", "edition"),
        Release: TargetMetadata("release", "release"),
        Platform: TargetMetadata("platform", "platform"),
    }
    try:
        return target_metadata[type(target)]
    except KeyError as error:
        raise ValidationError({"target": "Unsupported catalog target."}) from error


#: Sharing is unsettled until #783, #784, #785.
SHARED_TARGET = "A shared record's references cannot be changed here."
OTHER_LIBRARY_TARGET = "This record belongs to another library."
REMOVED_TARGET = "This record was removed. Put it back before you change it."
KEY_TAKEN = "Another record already states this identifier."
#: Two writes raced; this record holds it.
RECORD_RACED = (
    "Another change reached this record's identifiers first. "
    "Nothing was saved; try again."
)


class ReferencesRefused(ValidationError):
    """A refusal and the box behind it."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class OwnerAndMark(NamedTuple):
    """Who holds a row, and whether removed."""

    library_id: UUID | None
    removed: bool


def _owner_and_mark(target: CatalogTarget) -> OwnerAndMark:
    """A child reads its ancestors' marks too."""
    from games.models import Edition, Game, Platform, Release

    if isinstance(target, Game | Platform):
        return OwnerAndMark(target.library_id, target.removed_at is not None)
    if isinstance(target, Edition):
        game = target.game
        return OwnerAndMark(
            game.library_id,
            target.removed_at is not None or game.removed_at is not None,
        )
    if isinstance(target, Release):
        edition = target.edition
        game = edition.game
        return OwnerAndMark(
            game.library_id,
            target.removed_at is not None
            or edition.removed_at is not None
            or game.removed_at is not None,
        )
    raise ValidationError({"target": "Unsupported catalog target."})


def _refuse_an_unwritable_target(target: CatalogTarget, library: UserLibrary) -> None:
    """Shared, foreign or removed records state nothing."""
    owner, removed = _owner_and_mark(target)
    if owner is None:
        raise ReferencesRefused(SHARED_TARGET)
    if owner != library.pk:
        raise ReferencesRefused(OTHER_LIBRARY_TARGET)
    if removed:
        raise ReferencesRefused(REMOVED_TARGET)


def _normalized_or_refused(provider: ProviderName, raw: str) -> ProviderKey:
    """A blank box states no reference."""
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
    wanted: Mapping[ProviderName, ProviderKey],
    held: Mapping[ProviderName, ExternalReference],
    entity_kind: str,
) -> None:
    """A key another live row already holds."""
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


def _refusal_for(
    collision: IntegrityError, provider: ProviderName, entity_kind: str
) -> ReferencesRefused | None:
    """What a constraint this write lost says."""
    diagnostic = getattr(collision.__cause__, "diag", None)
    name = None if diagnostic is None else diagnostic.constraint_name
    if name == "unique_external_reference_provider_kind_key":
        return ReferencesRefused(KEY_TAKEN, provider=provider)
    if name == f"unique_live_{entity_kind}_reference_per_provider":
        return ReferencesRefused(RECORD_RACED, provider=provider)
    return None


def _state_one(
    provider: ProviderName,
    provider_key: ProviderKey,
    incumbent: ExternalReference | None,
    target: CatalogTarget,
    entity_kind: str,
    column: str,
) -> None:
    """One box, as the writes it takes."""
    from games.models import ExternalReference

    if incumbent is not None:
        if incumbent.provider_key == provider_key:
            return
        ExternalReference.objects.filter(pk=incumbent.pk).update(removed_at=now())
    if not provider_key:
        return
    #: No pre-check wins a race.
    #:
    #: The lock above holds this record's rows, never the key
    #: another record is about to claim, thus the constraint
    #: answers the loser. The savepoint keeps the connection
    #: usable for that answer.
    try:
        with transaction.atomic():
            ExternalReference.objects.create(
                provider=provider,
                entity_kind=entity_kind,
                provider_key=provider_key,
                **{column: target},
            )
    except IntegrityError as collision:
        refusal = _refusal_for(collision, provider, entity_kind)
        if refusal is None:
            raise
        raise refusal from collision


def state_external_references(
    *,
    target: CatalogTarget,
    library: UserLibrary,
    keys: Mapping[ProviderName, str],
) -> None:
    """The whole desired set, for providers named.

    A provider the caller does not name is left alone: a writer
    that knows one provider must not take another's row.
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


def resolve_external_reference(
    *, provider: str, entity_kind: str, provider_key: str
) -> UUID | None:
    """Only a live row answers, or None."""
    from games.models import ExternalReference

    target_field = ExternalReference.TARGET_FIELDS.get(entity_kind)
    if target_field is None:
        raise ValidationError({"entity_kind": "Unsupported catalog entity kind."})
    target_id_field = f"{target_field}_id"

    provider, provider_key = normalize_provider_key(
        provider=provider, provider_key=provider_key
    )
    return (
        ExternalReference.objects.filter(
            provider=provider,
            entity_kind=entity_kind,
            provider_key=provider_key,
            removed_at__isnull=True,
        )
        .values_list(target_id_field, flat=True)
        .first()
    )


def mirror_game_wikidata(game: Game) -> None:
    """Write `Game.wikidata` from the reference stating it.

    An UPDATE rather than a save(), like `mirror_legacy_columns()`,
    so the mirror revalidates nothing and fires no signal. #889
    takes the column.
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
    """What the backfill wrote, and left."""

    written: int
    taken: int
    malformed: int


def backfill_wikidata_references(library: UserLibrary) -> BackfilledReferences:
    """A loaded Game's column becomes a reference.

    A removed Game is left alone: nothing may state a reference
    under a row a person took out, and the refusal would abort the
    whole load. A key another live row holds is left alone too,
    because #654 and #785 own that reconciliation.
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
