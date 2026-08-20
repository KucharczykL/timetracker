import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from django.core.exceptions import ValidationError

WIKIDATA_KEY_PATTERN = re.compile(r"Q[1-9][0-9]*")


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    normalize_key: Callable[[str], str]
    url_template: str


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
    ),
}


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().casefold()
    if normalized not in PROVIDER_POLICIES:
        raise ValidationError({"provider": "Unsupported external-reference provider."})
    return normalized


def normalize_provider_key(
    *, provider: str, provider_key: str
) -> tuple[str, str]:
    provider = normalize_provider(provider)
    return provider, PROVIDER_POLICIES[provider].normalize_key(provider_key)


def external_reference_url(
    *, provider: str, entity_kind: str, provider_key: str
) -> str:
    if entity_kind not in {"game", "edition", "release", "platform"}:
        raise ValidationError({"entity_kind": "Unsupported catalog entity kind."})
    provider, key = normalize_provider_key(
        provider=provider, provider_key=provider_key
    )
    policy = PROVIDER_POLICIES[provider]
    return policy.url_template.format(
        entity_kind=quote(entity_kind, safe=""),
        provider_key=quote(key, safe=""),
    )
