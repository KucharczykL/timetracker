"""Saved presets speak the projection's purchase words.

A walk over plain dicts, at any depth: the key
`purchase_filter` and a purchase aggregate's `scope` name a
purchase filter on every filter, so the walk needs no mode.
A preset holding a criterion no new field states stays as
it is, and its reason is printed.
"""

from typing import Any, NamedTuple

from django.db import migrations

type Node = dict[str, Any]

_OPERATORS = ("AND", "OR", "NOT")

#: Renamed whole, criterion kept.
_RENAMED = {
    "price": "amount",
    "price_currency": "currency",
    "converted_price": "valuation",
    "date_purchased": "purchased",
    "date_refunded": "refunded",
    "games": "game",
}
#: Kept as they are; the new words too.
_KEPT = {
    "platform",
    "name",
    "created_at",
    "search",
    "is_refunded",
    "match",
    "kind",
    "note",
    "amount",
    "currency",
    "price_state",
    "valuation",
    "purchased",
    "refunded",
    "access",
    "format",
    "game",
}
#: No field states these.
_UNEXPRESSIBLE = {
    "num_purchases",
    "needs_price_update",
    "converted_currency",
    "updated_at",
    "platform_filter",
    "field_comparisons",
}
_DATES = {"date_purchased", "date_refunded"}
_PRESENCE = {"IS_NULL", "NOT_NULL"}

#: The conversion's table: access, format, kind rule.
_OWNERSHIP: dict[str, tuple[list[str], str, Node | None]] = {
    "ph": (["owned"], "physical", None),
    "di": (["owned"], "digital", {"value": ["upgrade"], "modifier": "EXCLUDES"}),
    "du": (["owned"], "digital", {"value": ["upgrade"], "modifier": "INCLUDES"}),
    "re": (["rented", "subscription"], "digital", None),
    "bo": (["borrowed"], "physical", None),
    "tr": (["trial"], "digital", None),
    "de": (["demo"], "digital", None),
    "pi": (["pirated"], "unknown", None),
}
_PASSES = {"season_pass", "battle_pass"}

_AGGREGATES = ("purchase_count", "purchase_price_total")

#: Old sort key, new; None leaves the sort.
_SORTS: dict[str, str | None] = {"type": "kind", "price": "amount", "infinite": None}


class Rewritten(NamedTuple):
    node: Any
    #: Why a node could not be rewritten.
    unexpressible: list[str]


def _words(criterion: Node) -> list[str]:
    """A set criterion's values, labels dropped."""
    return [
        word["id"] if isinstance(word, dict) else word
        for word in criterion.get("value") or []
    ]


def _includes(criterion: Any) -> bool:
    return (
        isinstance(criterion, dict)
        and criterion.get("modifier", "INCLUDES") == "INCLUDES"
        and not criterion.get("excludes")
    )


def _choice(words: list[str], modifier: str = "INCLUDES") -> Node:
    return {"value": words, "modifier": modifier}


def _type_member(word: str) -> Node | None:
    if word == "game":
        return {
            "kind": _choice(["game"]),
            "game_filter": {"kind": _choice(["dlc"], "EXCLUDES")},
        }
    if word == "dlc":
        return {"kind": _choice(["game"]), "game_filter": {"kind": _choice(["dlc"])}}
    if word in _PASSES:
        return {"kind": _choice([word])}
    return None


def _ownership_member(word: str) -> Node | None:
    if word not in _OWNERSHIP:
        return None
    access, format, kind = _OWNERSHIP[word]
    member: Node = {
        "entry_filter": {"access": _choice(access), "format": _choice([format])}
    }
    if kind is not None:
        member["kind"] = kind
    return member


def _one_of(key: str, criterion: Any, member_of) -> Rewritten:
    """An `OR` member per word."""
    if not _includes(criterion):
        return Rewritten(None, [f"{key}: only 'includes' converts"])
    members = []
    for word in _words(criterion):
        member = member_of(word)
        if member is None:
            return Rewritten(None, [f"{key}: no new word for {word!r}"])
        members.append(member)
    return Rewritten({"OR": members}, [])


def rewrite_purchase_node(node: Any) -> Rewritten:
    """One purchase filter, and every node under it."""
    if not isinstance(node, dict):
        return Rewritten(node, [])
    result: Node = {}
    grouped: list[Node] = []
    unexpressible: list[str] = []
    for key, value in node.items():
        if key in _OPERATORS and isinstance(value, list):
            children = [rewrite_purchase_node(child) for child in value]
            result[key] = [child.node for child in children]
            for child in children:
                unexpressible += child.unexpressible
        elif key in ("game_filter", "entry_filter"):
            walked = rewrite_filter_tree(value)
            result[key] = walked.node
            unexpressible += walked.unexpressible
        elif key in _KEPT:
            result[key] = value
        elif key in _RENAMED:
            if (
                key in _DATES
                and isinstance(value, dict)
                and value.get("value") is None
                and value.get("modifier") not in _PRESENCE
            ):
                unexpressible.append(f"{key}: a stored date of None")
            elif key == "games" and not _includes(value):
                unexpressible.append("games: only 'includes' converts")
            result[_RENAMED[key]] = value
        elif key == "type":
            group = _one_of(key, value, _type_member)
            unexpressible += group.unexpressible
            grouped.append(group.node)
        elif key == "ownership_type":
            group = _one_of(key, value, _ownership_member)
            unexpressible += group.unexpressible
            grouped.append(group.node)
        elif key == "infinite":
            grouped.append({"game_filter": {"excluded_from_unfinished": value}})
        elif key in _UNEXPRESSIBLE:
            unexpressible.append(f"{key}: no field states it")
        else:
            unexpressible.append(f"{key}: an unknown key")
    if grouped:
        result["AND"] = [*result.get("AND", []), *grouped]
    return Rewritten(result, unexpressible)


def _legacy_operand(operand: Any) -> bool:
    if not isinstance(operand, str):
        return False
    hops = operand.split("__")
    return "purchases" in hops or "addon_purchases" in hops


def rewrite_filter_tree(node: Any) -> Rewritten:
    """Any filter; each purchase filter in it rewritten."""
    if isinstance(node, list):
        children = [rewrite_filter_tree(child) for child in node]
        return Rewritten(
            [child.node for child in children],
            [reason for child in children for reason in child.unexpressible],
        )
    if not isinstance(node, dict):
        return Rewritten(node, [])
    result: Node = {}
    unexpressible: list[str] = []
    for key, value in node.items():
        if key == "purchase_filter":
            walked = rewrite_purchase_node(value)
        elif key in _AGGREGATES and isinstance(value, dict) and "scope" in value:
            scope = rewrite_purchase_node(value["scope"])
            walked = Rewritten({**value, "scope": scope.node}, scope.unexpressible)
        elif key == "field_comparisons" and isinstance(value, list):
            reasons = [
                f"field_comparisons: {comparison.get(side)!r} is a legacy path"
                for comparison in value
                if isinstance(comparison, dict)
                for side in ("left", "right")
                if _legacy_operand(comparison.get(side))
            ]
            walked = Rewritten(value, reasons)
        else:
            walked = rewrite_filter_tree(value)
        result[key] = walked.node
        unexpressible += walked.unexpressible
    return Rewritten(result, unexpressible)


def rewrite_sort(find_filter: Any) -> Any:
    """Sort tokens renamed, signs kept."""
    if not isinstance(find_filter, dict):
        return find_filter
    sort = find_filter.get("sort")
    if not isinstance(sort, str) or not sort:
        return find_filter
    tokens = []
    for token in sort.split(","):
        descending = token.startswith("-")
        key = token[1:] if descending else token
        renamed = _SORTS.get(key, key)
        if renamed is not None:
            tokens.append(("-" if descending else "") + renamed)
    return {**find_filter, "sort": ",".join(tokens)}


def rewrite_preset(
    mode: str, object_filter: Any, find_filter: Any
) -> tuple[Any, Any, list[str]]:
    """A preset's filter and sort, and what refused."""
    if mode == "purchases":
        walked = rewrite_purchase_node(object_filter)
        return walked.node, rewrite_sort(find_filter), walked.unexpressible
    walked = rewrite_filter_tree(object_filter)
    return walked.node, find_filter, walked.unexpressible


def rewrite_forward(apps, schema_editor):
    """Rewrite every preset; report what stays.

    A plain walk, not `.iterator()`: a preset table holds
    tens of rows. The count is printed, so a run that
    touched nothing reads apart from one against the
    wrong database.
    """
    preset_model = apps.get_model("games", "FilterPreset")
    presets = list(preset_model.objects.all())
    rewritten_count = 0
    for preset in presets:
        object_filter, find_filter, unexpressible = rewrite_preset(
            preset.mode, preset.object_filter, preset.find_filter
        )
        if unexpressible:
            for reason in unexpressible:
                print(f"  preset {preset.pk} {preset.name!r} kept: {reason}")
            continue
        if (object_filter, find_filter) == (preset.object_filter, preset.find_filter):
            continue
        preset.object_filter = object_filter
        preset.find_filter = find_filter
        preset.save(update_fields=["object_filter", "find_filter"])
        rewritten_count += 1
    print(f"  presets rewritten: {rewritten_count}/{len(presets)}")


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0031_purchase_conversion"),
    ]

    operations = [
        migrations.RunPython(rewrite_forward, migrations.RunPython.noop, elidable=True),
    ]
