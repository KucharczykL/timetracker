from random import choices as random_choices
from string import ascii_lowercase
from typing import Any, Callable

from django.template import TemplateDoesNotExist
from django.template.defaultfilters import floatformat
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse
from django.utils.safestring import SafeText, mark_safe

from common.utils import truncate
from games.models import Edition, Game, Purchase, Session

HTMLAttribute = tuple[str, str | int | bool]
HTMLTag = str


def Component(
    attributes: list[HTMLAttribute] = [],
    children: list[HTMLTag] | HTMLTag = [],
    template: str = "",
    tag_name: str = "",
) -> HTMLTag:
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
        tag = render_to_string(
            template,
            {name: value for name, value in attributes}
            | {"slot": mark_safe("\n".join(children))},
        )
    return mark_safe(tag)


def randomid(seed: str = "", length: int = 10) -> str:
    return seed + "".join(random_choices(ascii_lowercase, k=length))


def Popover(
    popover_content: str,
    wrapped_content: str = "",
    wrapped_classes: str = "",
    children: list[HTMLTag] = [],
    attributes: list[HTMLAttribute] = [],
) -> str:
    if not wrapped_content and not children:
        raise ValueError("One of wrapped_content or children is required.")
    id = randomid()
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
    attributes: list[HTMLAttribute] = [],
    children: list[HTMLTag] | HTMLTag = [],
    url: str | Callable[..., Any] = "",
):
    """
    Returns the HTML tag "a".
    "url" can either be:
        - URL (string)
        - path name passed to reverse() (string)
        - function
    """
    additional_attributes = []
    if url:
        if type(url) is str:
            try:
                url_result = reverse(url)
            except NoReverseMatch:
                url_result = url
        elif callable(url):
            url_result = url()
        else:
            raise TypeError("'url' is neither str nor function.")
        additional_attributes = [("href", url_result)]
    return Component(
        tag_name="a", attributes=attributes + additional_attributes, children=children
    )


def Button(
    attributes: list[HTMLAttribute] = [],
    children: list[HTMLTag] | HTMLTag = [],
    size: str = "base",
    icon: bool = False,
    color: str = "blue",
):
    return Component(
        template="cotton/button.html",
        attributes=attributes + [("size", size), ("icon", icon), ("color", color)],
        children=children,
    )


def Div(
    attributes: list[HTMLAttribute] = [],
    children: list[HTMLTag] | HTMLTag = [],
):
    return Component(tag_name="div", attributes=attributes, children=children)


def Input(
    type: str = "text",
    attributes: list[HTMLAttribute] = [],
    children: list[HTMLTag] | HTMLTag = [],
):
    return Component(
        tag_name="input", attributes=attributes + [("type", type)], children=children
    )


def Form(
    action="",
    method="get",
    attributes: list[HTMLAttribute] = [],
    children: list[HTMLTag] | HTMLTag = [],
):
    return Component(
        tag_name="form",
        attributes=attributes + [("action", action), ("method", method)],
        children=children,
    )


def Icon(
    name: str,
    attributes: list[HTMLAttribute] = [],
):
    try:
        result = Component(template=f"cotton/icon/{name}.html", attributes=attributes)
    except TemplateDoesNotExist:
        result = Icon(name="unspecified", attributes=attributes)
    return result


def LinkedPurchase(purchase: Purchase) -> SafeText:
    link = reverse("view_purchase", args=[int(purchase.id)])
    link_content = ""
    popover_content = ""
    edition_count = purchase.editions.count()
    popover_if_not_truncated = False
    if edition_count == 1:
        link_content += purchase.editions.first().name
        popover_content = link_content
    if edition_count > 1:
        if purchase.name:
            link_content += f"{purchase.name}"
            popover_content += f"<h1>{purchase.name}</h1><br>"
        else:
            link_content += f"{edition_count} games"
            popover_if_not_truncated = True
        popover_content += f"""
        <ul class="list-disc list-inside">
            {"".join(f"<li>{edition.name}</li>" for edition in purchase.editions.all())}
        </ul>
        """
    icon = purchase.platform.icon if edition_count == 1 else "unspecified"
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
    return mark_safe(A(url=link, children=[a_content]))


def NameWithIcon(
    name: str = "",
    platform: str = "",
    game_id: int = 0,
    session_id: int = 0,
    purchase_id: int = 0,
    edition_id: int = 0,
    linkify: bool = True,
    emulated: bool = False,
) -> SafeText:
    create_link = False
    link = ""
    edition = None
    platform = None
    if (
        game_id != 0 or session_id != 0 or purchase_id != 0 or edition_id != 0
    ) and linkify:
        create_link = True
        if session_id:
            session = Session.objects.get(pk=session_id)
            emulated = session.emulated
            edition = session.purchase.first_edition
            game_id = edition.game.pk
        if purchase_id:
            purchase = Purchase.objects.get(pk=purchase_id)
            edition = purchase.first_edition
            game_id = purchase.edition.game.pk
        if edition_id:
            edition = Edition.objects.get(pk=edition_id)
            game_id = edition.game.pk
        if game_id:
            game = Game.objects.get(pk=game_id)
        name = edition.name if edition else game.name
        platform = edition.platform if edition else None
        link = reverse("view_game", args=[int(game_id)])
    content = Div(
        [("class", "inline-flex gap-2 items-center")],
        [
            Icon(
                platform.icon,
                [("title", platform.name)],
            )
            if platform
            else "",
            Icon("emulated", [("title", "Emulated")]) if emulated else "",
            PopoverTruncated(name),
        ],
    )

    return mark_safe(
        A(
            url=link,
            children=[content],
        )
        if create_link
        else content,
    )


def PurchasePrice(purchase) -> str:
    return Popover(
        popover_content=f"{floatformat(purchase.price)} {purchase.price_currency}",
        wrapped_content=f"{floatformat(purchase.converted_price)} {purchase.converted_currency}",
        wrapped_classes="underline decoration-dotted",
    )
