import hashlib
import json
from functools import lru_cache
from typing import Any

from django.conf import settings
from django.template import TemplateDoesNotExist
from django.template.defaultfilters import floatformat
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.safestring import SafeText, mark_safe

from common.utils import truncate
from games.models import Game, Purchase, Session

HTMLAttribute = tuple[str, str | int | bool]
HTMLTag = str


def _render_cached_impl(template: str, context_json: str) -> str:
    context = json.loads(context_json)
    context["slot"] = mark_safe(context["slot"])
    return render_to_string(template, context)


if not settings.DEBUG:
    _render_cached = lru_cache(maxsize=4096)(_render_cached_impl)
else:
    _render_cached = _render_cached_impl


def enable_cache():
    """Wrap _render_cached with LRU cache (for testing in DEBUG mode)."""
    global _render_cached
    _render_cached = lru_cache(maxsize=4096)(_render_cached_impl)


def Component(
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
    template: str = "",
    tag_name: str = "",
) -> SafeText:
    attributes = attributes or []
    children = children or []
    if not tag_name and not template:
        raise ValueError("One of template or tag_name is required.")
    if isinstance(children, str):
        children = [children]
    childrenBlob = "\n".join(children)
    if len(attributes) == 0:
        attributesBlob = ""
    else:
        attributesList = [f'{name}="{value}"' for name, value in attributes]
        # make attribute list into a string
        # and insert space between tag and attribute list
        attributesBlob = f" {' '.join(attributesList)}"
    tag: str = ""
    if tag_name != "":
        tag = f"<{tag_name}{attributesBlob}>{childrenBlob}</{tag_name}>"
    elif template != "":
        context = {name: value for name, value in attributes} | {"slot": "\n".join(children)}
        tag = _render_cached(template, json.dumps(context, sort_keys=True))
    return mark_safe(tag)


def randomid(seed: str = "", content: str = "", length: int = 10) -> str:
    if not seed and not content:
        return seed
    hash_input = f"{seed}:{content}" if seed else content
    content_hash = hashlib.sha1(hash_input.encode()).hexdigest()
    base = content_hash[:length] if not seed else content_hash[:max(0, length - len(seed))]
    return seed + base


def Popover(
    popover_content: str,
    wrapped_content: str = "",
    wrapped_classes: str = "",
    children: list[HTMLTag] | None = None,
    attributes: list[HTMLAttribute] | None = None,
) -> str:
    attributes = attributes or []
    children = children or []
    if not wrapped_content and not children:
        raise ValueError("One of wrapped_content or children is required.")
    id = randomid(content=f"{wrapped_content}:{popover_content}:{wrapped_classes}")
    return Component(
        attributes=attributes
        + [
            ("id", id),
            ("wrapped_content", wrapped_content),
            ("popover_content", popover_content),
            ("wrapped_classes", wrapped_classes),
        ],
        children=children,
        template="cotton/popover.html",
    )


def PopoverTruncated(
    input_string: str,
    popover_content: str = "",
    popover_if_not_truncated: bool = False,
    length: int = 30,
    ellipsis: str = "…",
    endpart: str = "",
) -> str:
    """
    Returns `input_string` truncated after `length` of characters
    and displays the untruncated text in a popover HTML element.
    The truncated text ends in `ellipsis`, and optionally
    an always-visible `endpart` can be specified.
    `popover_content` can be specified if:
    1. It needs to be always displayed regardless if text is truncated.
    2. It needs to differ from `input_string`.
    """
    if (truncated := truncate(input_string, length, ellipsis, endpart)) != input_string:
        return Popover(
            wrapped_content=truncated,
            popover_content=popover_content if popover_content else input_string,
        )
    else:
        if popover_content and popover_if_not_truncated:
            return Popover(
                wrapped_content=input_string,
                popover_content=popover_content if popover_content else "",
            )
        else:
            return input_string


def A(
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
    url_name: str | None = None,
    href: str | None = None,
) -> SafeText:
    """
    Returns an anchor <a> tag.

    Accepts one of two mutually-exclusive URL specifications:
        - url_name: URL pattern name, resolved via reverse()
        - href: Literal path string passed through as-is
    """
    attributes = attributes or []
    children = children or []
    if url_name is not None and href is not None:
        raise ValueError("Provide exactly one of 'url_name' or 'href', not both.")

    additional_attributes = []
    if url_name is not None:
        additional_attributes = [("href", reverse(url_name))]
    elif href is not None:
        additional_attributes = [("href", href)]
    return Component(
        tag_name="a", attributes=attributes + additional_attributes, children=children
    )


def Button(
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
    size: str = "base",
    icon: bool = False,
    color: str = "blue",
) -> SafeText:
    attributes = attributes or []
    children = children or []
    return Component(
        template="cotton/button.html",
        attributes=attributes
        + [
            ("size", size),
            ("icon", icon),
            ("color", color),
            ("class", "hover:cursor-pointer"),
        ],
        children=children,
    )


def Div(
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    attributes = attributes or []
    children = children or []
    return Component(tag_name="div", attributes=attributes, children=children)


def Input(
    type: str = "text",
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    attributes = attributes or []
    children = children or []
    return Component(
        tag_name="input", attributes=attributes + [("type", type)], children=children
    )


def Form(
    action="",
    method="get",
    attributes: list[HTMLAttribute] | None = None,
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    attributes = attributes or []
    children = children or []
    return Component(
        tag_name="form",
        attributes=attributes + [("action", action), ("method", method)],
        children=children,
    )


def Icon(
    name: str,
    attributes: list[HTMLAttribute] | None = None,
) -> SafeText:
    attributes = attributes or []
    try:
        result = Component(template=f"cotton/icon/{name}.html", attributes=attributes)
    except TemplateDoesNotExist:
        result = Icon(name="unspecified", attributes=attributes)
    return result


def LinkedPurchase(purchase: Purchase) -> SafeText:
    link = reverse("view_purchase", args=[int(purchase.id)])
    link_content = ""
    popover_content = ""
    game_count = purchase.games.count()
    popover_if_not_truncated = False
    if game_count == 1:
        link_content += purchase.games.first().name
        popover_content = link_content
    if game_count > 1:
        if purchase.name:
            link_content += f"{purchase.name}"
            popover_content += f"<h1>{purchase.name}</h1><br>"
        else:
            link_content += f"{game_count} games"
            popover_if_not_truncated = True
        popover_content += f"""
        <ul class="list-disc list-inside">
            {"".join(f"<li>{game.name}</li>" for game in purchase.games.all())}
        </ul>
        """
    icon = purchase.platform.icon if game_count == 1 else "unspecified"
    if link_content == "":
        raise ValueError("link_content is empty!!")
    a_content = Div(
        [("class", "inline-flex gap-2 items-center")],
        [
            Icon(
                icon,
                [("title", "Multiple")],
            ),
            PopoverTruncated(
                input_string=link_content,
                popover_content=mark_safe(popover_content),
                popover_if_not_truncated=popover_if_not_truncated,
            ),
        ],
    )
    return A(href=link, children=[a_content])


def NameWithIcon(
    name: str = "",
    game: Game | None = None,
    session: Session | None = None,
    linkify: bool = True,
    emulated: bool = False,
) -> SafeText:
    _name, platform, final_emulated, create_link, link = _resolve_name_with_icon(
        name, game, session, linkify
    )

    content = Div(
        [("class", "inline-flex gap-2 items-center")],
        [
            Icon(
                platform.icon,
                [("title", platform.name)],
            )
            if platform
            else "",
            Icon("emulated", [("title", "Emulated")]) if final_emulated else "",
            PopoverTruncated(_name),
        ],
    )

    return (
        A(
            href=link,
            children=[content],
        )
        if create_link
        else content
    )


def _resolve_name_with_icon(
    name: str,
    game: Game | None,
    session: Session | None,
    linkify: bool,
) -> tuple[str, Any, bool, bool, str]:
    create_link = False
    link = ""
    platform = None
    final_emulated = False

    if session is not None:
        game = session.game
        platform = game.platform
        final_emulated = session.emulated
        if linkify:
            create_link = True
            link = reverse("view_game", args=[int(game.pk)])
    elif game is not None:
        platform = game.platform
        if linkify:
            create_link = True
            link = reverse("view_game", args=[int(game.pk)])

    _name = name or (game.name if game else "")

    return _name, platform, final_emulated, create_link, link


def PurchasePrice(purchase) -> SafeText:
    return Popover(
        popover_content=f"{floatformat(purchase.price)} {purchase.price_currency}",
        wrapped_content=f"{floatformat(purchase.converted_price)} {purchase.converted_currency}",
        wrapped_classes="underline decoration-dotted",
    )



