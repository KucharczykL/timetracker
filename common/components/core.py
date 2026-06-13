"""Node layer: the lazy component tree, its renderer, and media collection.

A FastHTML-style model. Everything renderable is a :class:`Node`. The single
:class:`Element` class represents *any* HTML element (tag + attrs + children);
named builders like ``Div`` / ``Span`` are generated from a whitelist rather
than hand-written per tag (see ``primitives.py``). Higher-level, behaviour- or
media-bearing components subclass :class:`BaseComponent` and implement
``render()`` returning a node subtree.

Nodes are *lazy*: they hold structure and render to HTML only when asked
(``str(node)`` / ``node.__html__()`` / :func:`render`). This is what lets
``Page()`` walk a finished tree and collect every component's declared JS
(:class:`Media`) instead of each view threading ``scripts=`` by hand.
"""

import hashlib
from collections.abc import Sequence
from functools import lru_cache

from django.utils.html import escape
from django.utils.safestring import SafeText, mark_safe


HTMLAttribute = tuple[str, str | int | bool]


# Type for a builder's ``attributes`` parameter. Covariant ``Sequence`` so a
# caller's ``list[tuple[str, str]]`` is accepted (a plain ``list[HTMLAttribute]``
# would be invariant and reject it). Locals that get ``.append()``-ed should
# stay a concrete ``list[HTMLAttribute]``.
Attributes = Sequence[HTMLAttribute]


HTMLTag = str


# ── Media: declarative JS dependencies ──────────────────────────────────────


def _dedup(*sequences: tuple[str, ...]) -> tuple[str, ...]:
    """First-seen dedup that preserves declaration order across sequences."""
    seen: dict[str, None] = {}
    for sequence in sequences:
        for item in sequence:
            seen.setdefault(item, None)
    return tuple(seen)


class Media:
    """A component's JS dependencies, modelled on ``django.forms.Media``.

    ``js`` are static ES-module filenames (rendered as ``ModuleScript``);
    ``js_external`` are vendored UMD / classic bundles (rendered as
    ``StaticScript``). Addition merges with first-seen, order-preserving dedup,
    so a page that uses a component many times emits each script once.
    """

    __slots__ = ("js", "js_external")

    def __init__(
        self,
        js: tuple[str, ...] | list[str] = (),
        js_external: tuple[str, ...] | list[str] = (),
    ) -> None:
        self.js = tuple(js)
        self.js_external = tuple(js_external)

    def __add__(self, other: "Media | None") -> "Media":
        if not other:
            return self
        return Media(
            _dedup(self.js, other.js),
            _dedup(self.js_external, other.js_external),
        )

    def __radd__(self, other: "Media | None") -> "Media":
        # Supports ``sum(medias, Media())`` and ``0 + media``.
        if not other or other == 0:
            return self
        return other.__add__(self)

    def __bool__(self) -> bool:
        return bool(self.js or self.js_external)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Media)
            and self.js == other.js
            and self.js_external == other.js_external
        )

    def __hash__(self) -> int:
        return hash((self.js, self.js_external))

    def __repr__(self) -> str:
        return f"Media(js={self.js!r}, js_external={self.js_external!r})"


# ── Node tree ────────────────────────────────────────────────────────────────


class Node:
    """Base class for everything renderable to HTML."""

    # Declared dependencies. Class-level default is shared and empty; concrete
    # components override with their own ``Media(...)``.
    media: Media = Media()

    def _render(self) -> str:
        raise NotImplementedError

    def collect_media(self) -> Media:
        """Total media of this node and its subtree."""
        return self.media

    def with_media(self, media: Media) -> "Node":
        """Attach JS dependencies to this node and return it (for fluent use).

        Lets a function-built node declare its media without becoming a full
        ``BaseComponent`` subclass: ``return Div(...).with_media(Media(js=...))``.
        """
        self.media = self.media + media
        return self

    # A node's rendered output is always safe HTML by construction (Element
    # escapes unsafe children; Safe wraps trusted markup; Fragment escapes plain
    # strings). So both `__html__` (Django's conditional_escape hook) and
    # `__str__` return a SafeString — this is what keeps ``str(node)`` safe when
    # fed back into a child list or template, matching the old SafeText shims.
    def __html__(self) -> SafeText:
        return mark_safe(self._render())

    def __str__(self) -> SafeText:
        return mark_safe(self._render())


# A renderable child is a node or a string. Strings are ALWAYS escaped (a string
# is untrusted text — ``SafeText``/``mark_safe`` is escaped too); trusted
# pre-rendered HTML must be a ``Safe`` node. ``Children`` is the type for a
# builder's ``children``
# parameter: a sequence of child nodes/strings, a bare string, or nothing. The
# sequence is a covariant ``Sequence`` so ``list[Element]`` / ``list[Node]`` are
# accepted (a plain ``list[str]`` would be invariant and reject them). A single
# bare ``Node`` is accepted only by ``Element`` itself (which wraps it); the
# higher-level builders take ``Children``.
Child = Node | str
Children = Sequence[Child] | Node | str | None


def as_children(children: Children) -> list[Child]:
    """Normalise a builder's ``children`` argument to a flat list.

    Accepts ``None`` (→ empty), a single node/string (→ one-element list), or a
    sequence of them. Lets builders drop the ``children if isinstance(children,
    list) else [children]`` dance and get a properly typed ``list[Child]``.
    """
    if children is None:
        return []
    if isinstance(children, (str, Node)):
        return [children]
    return list(children)


def as_attributes(attributes: "Attributes | None") -> list[HTMLAttribute]:
    """Normalise an ``attributes`` argument to a mutable ``list[HTMLAttribute]``.

    Builders take a covariant ``Attributes`` (so callers can pass a
    ``list[tuple[str, str]]``) but often append to or concatenate the value;
    this turns it into a concrete list they can mutate.
    """
    return list(attributes) if attributes else []


def _child_key(child: object) -> tuple[str, bool]:
    """Normalise a child to a ``(text, is_safe)`` pair.

    Only :class:`Node` children render unescaped — that includes :class:`Safe`,
    the one sanctioned way to put trusted pre-rendered HTML into the tree. Every
    *string* child is escaped, ``SafeText``/``mark_safe`` included: a string is
    always treated as untrusted text, so trusted markup must be wrapped in
    ``Safe(...)`` rather than smuggled in as a safe string. ``is_safe`` is part
    of the render cache key so a safe ``"<b>"`` and an unsafe ``"<b>"`` never
    collide.
    """
    if isinstance(child, Node):
        return (child._render(), True)
    if isinstance(child, str):
        return (child, False)
    return (str(child), False)


@lru_cache(maxsize=4096)
def _render_element(
    tag_name: str,
    attrs_key: tuple[tuple[str, str], ...],
    children_key: tuple[tuple[str, bool], ...],
) -> str:
    """Pure, memoized HTML builder. Identical (tag, attrs, children) render once.

    ``attrs_key`` is (name, stringified value) pairs (values always escaped);
    ``children_key`` is (text, is_safe) pairs (safe passes through, else escaped).
    """
    children_blob = "\n".join(
        child if is_safe else escape(child) for child, is_safe in children_key
    )
    if attrs_key:
        attributes_blob = " " + " ".join(
            f'{name}="{escape(value)}"' for name, value in attrs_key
        )
    else:
        attributes_blob = ""
    return f"<{tag_name}{attributes_blob}>{children_blob}</{tag_name}>"


class Element(Node):
    """Any HTML element: a tag name, attributes and children.

    Children may be other nodes, ``SafeText``, or plain strings (escaped).
    Rendering goes through the memoized :func:`_render_element`.
    """

    def __init__(
        self,
        tag_name: str,
        attributes: Attributes | None = None,
        children: "Children | Node" = None,
    ) -> None:
        if not tag_name:
            raise ValueError("tag_name is required.")
        self.tag_name = tag_name
        self.attributes = attributes or []
        if children is None:
            children = []
        elif isinstance(children, (str, Node)):
            children = [children]
        self.children = children

    def collect_media(self) -> Media:
        media = self.media
        for child in self.children:
            if isinstance(child, Node):
                media = media + child.collect_media()
        return media

    def _render(self) -> str:
        attrs_key = tuple((name, str(value)) for name, value in self.attributes)
        children_key = tuple(_child_key(child) for child in self.children)
        return _render_element(self.tag_name, attrs_key, children_key)


class Safe(Node):
    """A node wrapping pre-rendered, trusted HTML (the ``mark_safe`` analogue).

    Used as the migration bridge for components still built from f-strings:
    they return ``Safe(html)`` and declare their ``media`` explicitly rather
    than atomising their markup into a node tree up front.
    """

    def __init__(self, html: object, media: Media | None = None) -> None:
        self._html = str(html)
        if media is not None:
            self.media = media

    def _render(self) -> str:
        return self._html


class Fragment(Node):
    """An ordered group of children with no wrapping tag.

    Replaces ``mark_safe(str(a) + str(b))`` / ``"\\n".join(...)`` composition,
    so media still bubbles up from the grouped children.
    """

    def __init__(self, *children: object, separator: str = "") -> None:
        self.children = [c for c in children if c is not None and c != ""]
        self.separator = separator

    def collect_media(self) -> Media:
        media = Media()
        for child in self.children:
            if isinstance(child, Node):
                media = media + child.collect_media()
        return media

    def _render(self) -> str:
        parts = []
        for child in self.children:
            text, is_safe = _child_key(child)
            parts.append(text if is_safe else escape(text))
        return self.separator.join(parts)


class BaseComponent(Node):
    """Base for higher-level components: implement ``render()`` returning a node
    subtree and declare ``media`` (a :class:`Media`).

    ``render()`` is called once and memoized; ``collect_media()`` returns this
    component's own media merged with the rendered subtree's.
    """

    def render(self) -> Node:
        raise NotImplementedError

    def _tree(self) -> Node:
        cached = getattr(self, "_tree_cache", None)
        if cached is None:
            cached = self.render()
            self._tree_cache = cached
        return cached

    def _render(self) -> str:
        return self._tree()._render()

    def collect_media(self) -> Media:
        return self.media + self._tree().collect_media()


def render(node: "Node | str") -> SafeText:
    """Render a node (or pass a string through) to safe HTML."""
    if isinstance(node, Node):
        return mark_safe(node._render())
    return mark_safe(str(node))


def collect_media(node: "Node | str") -> Media:
    """Collect the media of a node tree (empty for a bare string)."""
    if isinstance(node, Node):
        return node.collect_media()
    return Media()


def randomid(seed: str = "", content: str = "", length: int = 10) -> str:
    if not seed and not content:
        return seed
    hash_input = f"{seed}:{content}" if seed else content
    content_hash = hashlib.sha1(hash_input.encode()).hexdigest()
    base = (
        content_hash[:length]
        if not seed
        else content_hash[: max(0, length - len(seed))]
    )
    return seed + base
