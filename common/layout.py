"""A small fast_app-style layout system.

Instead of Django template inheritance (`{% extends "base.html" %}`), views
build their page body with Python components and wrap it with `TimetrackerDocument()` /
`render_page()`. `TimetrackerDocument()` is the equivalent of FastHTML's document wrapper:
it hoists shared `<head>` content (the `_HEADERS` block, analogous to
`fast_app(hdrs=...)`), renders the navbar, and assembles the full document.
"""

import json
from typing import TYPE_CHECKING

from django.contrib.messages import get_messages
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.urls import reverse
from django.utils.safestring import SafeText
from django_htmx.jinja import django_htmx_script

from common.components.core import Document, Safe
from common.components.primitives import (
    CONTENT_MAX_WIDTH_CLASS,
    Body,
    Button,
    Div,
    Head,
    Html,
    Img,
    Link,
    Meta,
    Nav,
    Script,
    Span,
    Title,
)
from games.templatetags.version import version, version_date

if TYPE_CHECKING:
    from common.components import Node

# Static head script that sets the dark/light class before paint (avoids FOUC).
# Bare JS body — emitted inside a `Script()` node (a raw-text element).
_THEME_FOUC_SCRIPT = """
            if (localStorage.getItem('color-theme') === 'dark' || (!('color-theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
                document.documentElement.classList.add('dark');
            } else {
                document.documentElement.classList.remove('dark')
            }
        """

# The main module script: crown icon mount + theme-toggle wiring.
# Bare JS body (no `<script>` wrapper) — split around the single dynamic value
# (game.mastered) and emitted inside a `Script(type="module")` node.
_MAIN_SCRIPT_A = """
            document.addEventListener('DOMContentLoaded', () => {
                if (window.mountCrownIcon) {
                    window.mountCrownIcon('#crown-icon-mount-point', {
                        mastered: """
_MAIN_SCRIPT_B = """
                    });
                }

                const themeToggleDarkIcon = document.getElementById('theme-toggle-dark-icon');
                const themeToggleLightIcon = document.getElementById('theme-toggle-light-icon');
                const themeToggleBtn = document.getElementById('theme-toggle');

                if (themeToggleDarkIcon && themeToggleLightIcon && themeToggleBtn) {
                    if (document.documentElement.classList.contains('dark')) {
                        themeToggleLightIcon.classList.remove('hidden');
                        themeToggleDarkIcon.classList.add('hidden');
                    } else {
                        themeToggleDarkIcon.classList.remove('hidden');
                        themeToggleLightIcon.classList.add('hidden');
                    }

                    themeToggleBtn.addEventListener('click', function () {
                        themeToggleDarkIcon.classList.toggle('hidden');
                        themeToggleLightIcon.classList.toggle('hidden');

                        if (localStorage.getItem('color-theme')) {
                            if (localStorage.getItem('color-theme') === 'light') {
                                document.documentElement.classList.add('dark');
                                localStorage.setItem('color-theme', 'dark');
                            } else {
                                document.documentElement.classList.remove('dark');
                                localStorage.setItem('color-theme', 'light');
                            }
                        } else {
                            if (document.documentElement.classList.contains('dark')) {
                                document.documentElement.classList.remove('dark');
                                localStorage.setItem('color-theme', 'light');
                            } else {
                                document.documentElement.classList.add('dark');
                                localStorage.setItem('color-theme', 'dark');
                            }
                        }
                    });
                }
            });
        """

# Toast notification region (Alpine.js). Verbatim from the old base.html.
_TOAST_CONTAINER = """<div x-data="toastStore()"
         role="region"
         aria-label="Notifications"
         aria-atomic="true"
         class="fixed z-50 bottom-0 right-0 flex flex-col items-end pointer-events-none p-4">
        <template x-for="toast in $store.toasts.toasts" :key="toast.id">
            <div x-show="toast.visible"
                 x-transition:enter="transition ease-out duration-300"
                 x-transition:enter-start="opacity-0 translate-x-8"
                 x-transition:enter-end="opacity-100 translate-x-0"
                 x-transition:leave="transition ease-in duration-200"
                 x-transition:leave-start="opacity-100 translate-x-0"
                 x-transition:leave-end="opacity-0 translate-x-8"
                 :role="toast.type === 'error' || toast.type === 'warning' ? 'alert' : 'status'"
                  :aria-live="toast.type === 'error' ? 'assertive' : 'polite'"
                 tabindex="0"
                 class="pointer-events-auto max-w-sm w-72 cursor-pointer mb-3 last:mb-0"
     :class="{
                      'success': toast.type === 'success',
                      'error': toast.type === 'error',
                      'info': toast.type === 'info',
                      'warning': toast.type === 'warning',
                      'debug': toast.type === 'debug'
                  }"
                 @click="dismissToast(toast.id)"
                 @mouseenter="$store.toasts.clearToastTimer(toast.id)"
                 @mouseleave="$store.toasts.resumeToastTimer(toast.id, 5000)"
                 @keydown.escape="dismissToast(toast.id)">
                <div class="rounded-lg shadow-lg p-4 flex items-start gap-3"
                     :class="{
                          'bg-green-50 dark:bg-green-900 border border-green-200 dark:border-green-700': toast.type === 'success',
                          'bg-red-50 dark:bg-red-900 border border-red-200 dark:border-red-700': toast.type === 'error',
                          'bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-700': toast.type === 'info',
                          'bg-amber-50 dark:bg-amber-900 border border-amber-200 dark:border-amber-700': toast.type === 'warning',
                          'bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700': toast.type === 'debug'
                      }">
                    <span class="flex-shrink-0 mt-0.5"
                   :class="{
                               'text-green-500': toast.type === 'success',
                               'text-red-500': toast.type === 'error',
                               'text-blue-500': toast.type === 'info',
                               'text-amber-500': toast.type === 'warning',
                               'text-gray-500': toast.type === 'debug'
                           }">
                        <template x-if="toast.type === 'success'">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                            </svg>
                        </template>
                        <template x-if="toast.type === 'error'">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                            </svg>
                        </template>
                        <template x-if="toast.type === 'info'">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M12 20a8 8 0 100-16 8 8 0 000 16z"/>
                            </svg>
                        </template>
                        <template x-if="toast.type === 'warning'">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 13l5 5 5-5M7 6l5 5 5-5"/>
                            </svg>
                        </template>
                        <template x-if="toast.type === 'debug'">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                            </svg>
                        </template>
                    </span>
                    <p class="flex-1 text-sm"
                        :class="{
                            'text-green-800 dark:text-green-200': toast.type === 'success',
                            'text-red-800 dark:text-red-200': toast.type === 'error',
                            'text-blue-800 dark:text-blue-200': toast.type === 'info',
                            'text-amber-800 dark:text-amber-200': toast.type === 'warning',
                            'text-gray-800 dark:text-gray-200': toast.type === 'debug'
                        }"
                       x-text="toast.message"></p>
                    <button @click.stop="dismissToast(toast.id)"
                            class="flex-shrink-0"
                            :class="{
                                'text-green-400 hover:text-green-600 dark:text-green-500 dark:hover:text-green-300': toast.type === 'success',
                                'text-red-400 hover:text-red-600 dark:text-red-500 dark:hover:text-red-300': toast.type === 'error',
                                'text-blue-400 hover:text-blue-600 dark:text-blue-500 dark:hover:text-blue-300': toast.type === 'info',
                                'text-amber-400 hover:text-amber-600 dark:text-amber-500 dark:hover:text-amber-300': toast.type === 'warning',
                                'text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300': toast.type === 'debug'
                            }">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>
            </div>
        </template>
    </div>"""


def _main_script(mastered: bool) -> str:
    return _MAIN_SCRIPT_A + ("true" if mastered else "false") + _MAIN_SCRIPT_B


def NavbarPlaytime(
    today_played: str,
    last_7_played: str,
    *,
    today_url: str | None = None,
    last_7_url: str | None = None,
    oob: bool = False,
) -> "Node":
    """The navbar 'Today · Last 7 days' totals. Carries a stable id so
    htmx endpoints can refresh it out-of-band after a session change.

    When ``today_url`` / ``last_7_url`` are given, each total links to the
    matching filtered session list."""
    from common.components import Safe

    def total(text: str, url: str | None) -> str:
        if not url:
            return text
        return f'<a href="{url}" class="hover:underline">{text}</a>'

    oob_attr = ' hx-swap-oob="true"' if oob else ""
    return Safe(
        f'<li id="navbar-playtime"{oob_attr} '
        'class="flex flex-col items-center text-xs">'
        '<span class="flex uppercase gap-1">Today'
        '<span class="">·</span>Last 7 days</span>'
        '<span class="flex items-center gap-1">'
        f"{total(today_played, today_url)}"
        '<span class="">·</span>'
        f"{total(last_7_played, last_7_url)}</span></li>"
    )


# Theme toggle sun/moon SVGs: kept as a Safe() snippet because the FOUC script in
# TimetrackerDocument() targets their ids (theme-toggle-dark-icon / -light-icon). The hamburger
# is a plain icon, so it lives in the icon system (Icon("hamburger")).
_THEME_TOGGLE_SVGS = (
    '<svg id="theme-toggle-dark-icon" class="hidden w-5 h-5" fill="currentColor" '
    'viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path '
    'd="M3.32031 11.6835C3.32031 16.6541 7.34975 20.6835 12.3203 20.6835C16.1075 '
    "20.6835 19.3483 18.3443 20.6768 15.032C19.6402 15.4486 18.5059 15.6834 "
    "17.3203 15.6834C12.3497 15.6834 8.32031 11.654 8.32031 6.68342C8.32031 "
    "5.50338 8.55165 4.36259 8.96453 3.32996C5.65605 4.66028 3.32031 7.89912 "
    '3.32031 11.6835Z" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    '<svg id="theme-toggle-light-icon" class="hidden w-5 h-5" fill="currentColor" '
    'viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path '
    'd="M12 3V4M12 20V21M4 12H3M6.31412 6.31412L5.5 5.5M17.6859 6.31412L18.5 '
    "5.5M6.31412 17.69L5.5 18.5001M17.6859 17.69L18.5 18.5001M21 12H20M16 "
    "12C16 14.2091 14.2091 16 12 16C9.79086 16 8 14.2091 8 12C8 9.79086 9.79086 "
    '8 12 8C14.2091 8 16 9.79086 16 12Z" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

# Shared classes for the plain navbar entries (Home/Stats/Log out).
_NAV_LINK_CLASS = (
    "block py-2 px-3 rounded-sm hover:bg-gray-100 "
    "md:hover:bg-transparent md:border-0 md:hover:text-blue-700 md:p-0 "
    "text-heading md:dark:hover:text-blue-500 dark:hover:bg-gray-700 "
    "md:dark:hover:bg-transparent"
)


def NavbarMenu(
    *,
    today_played: str,
    last_7_played: str,
    today_url: str | None,
    last_7_url: str | None,
    current_year: int,
    csrf_token: str,
) -> "Node":
    """The responsive ``#navbar-dropdown`` collapse menu, built from components."""
    from common.components import (
        A,
        Button,
        Div,
        DropdownLinkItem,
        DropdownSubmenu,
        Form,
        Input,
        Li,
        MenuDropdown,
        Safe,
        Ul,
    )

    def entity_submenu(label, slug, add_url, list_url):
        return DropdownSubmenu(
            label,
            id=f"navbarMenu{slug}",
            items=[
                DropdownLinkItem(reverse(add_url), f"Add {label.lower()}"),
                DropdownLinkItem(reverse(list_url), f"List {label.lower()}s"),
            ],
        )

    theme_toggle = Li(class_="flex items-center")[
        Button(
            id_="theme-toggle",
            type="button",
            class_="p-2 text-gray-500 dark:text-gray-400 hover:bg-gray-100 "
            "dark:hover:bg-gray-700 focus:outline-hidden focus:ring-4 "
            "focus:ring-gray-200 dark:focus:ring-gray-700 rounded-lg "
            "text-sm hover:cursor-pointer",
        )[Safe(_THEME_TOGGLE_SVGS)]
    ]

    home = Li()[
        A(
            href=reverse("games:index"),
            class_="block py-2 px-3 bg-blue-700 rounded-sm "
            "md:bg-transparent md:p-0 text-heading hover:text-blue-500 "
            "dark:bg-blue-600 md:dark:bg-transparent",
            aria_current="page",
        )["Home"]
    ]

    # One entity menu: each entity is a submenu of its actions (Add / List).
    entity_menu = Li()[
        MenuDropdown(
            label="Menu",
            id="navbarMenu",
            placement="bottom-center",
            items=[
                entity_submenu(
                    "Device", "Device", "games:add_device", "games:list_devices"
                ),
                entity_submenu("Game", "Game", "games:add_game", "games:list_games"),
                entity_submenu(
                    "Platform", "Platform", "games:add_platform", "games:list_platforms"
                ),
                entity_submenu(
                    "Play event",
                    "PlayEvent",
                    "games:add_playevent",
                    "games:list_playevents",
                ),
                entity_submenu(
                    "Purchase", "Purchase", "games:add_purchase", "games:list_purchases"
                ),
                entity_submenu(
                    "Session", "Session", "games:add_session", "games:list_sessions"
                ),
            ],
        )
    ]

    stats = Li()[
        A(
            href=reverse("games:stats_by_year", args=[current_year]),
            class_=_NAV_LINK_CLASS,
        )["Stats"]
    ]

    logout = Li()[
        Form(method="post", action=reverse("logout"))[
            Input(
                type="hidden",
                name="csrfmiddlewaretoken",
                value=csrf_token,
            ),
            Button(type="submit", class_=_NAV_LINK_CLASS)["Log out"],
        ]
    ]

    return Div(class_="hidden w-full md:block md:w-auto", id="navbar-dropdown")[
        Ul(
            class_="items-center flex flex-col font-medium p-4 md:p-0 mt-4 border "
            "border-gray-100 rounded-lg bg-gray-50 md:space-x-8 rtl:space-x-reverse "
            "md:flex-row md:mt-0 md:border-0 md:bg-white dark:bg-gray-800 "
            "md:dark:bg-gray-900 dark:border-gray-700"
        )[
            theme_toggle,
            NavbarPlaytime(
                today_played,
                last_7_played,
                today_url=today_url,
                last_7_url=last_7_url,
            ),
            home,
            entity_menu,
            stats,
            logout,
        ]
    ]


def Navbar(
    *,
    today_played: str,
    last_7_played: str,
    today_url: str | None = None,
    last_7_url: str | None = None,
    current_year: int,
    csrf_token: str,
) -> "Node":
    """Top navigation bar, assembled from components (logo + hamburger + menu)."""
    from common.components import A, Div, Icon, Span

    logo = static("icons/tesserae-icon-animated.svg")
    brand = A(
        href=reverse("games:index"),
        class_="flex items-center",
    )[
        Img(src=logo, alt="Timetracker Logo", class_="w-10 h-10"),
        Span(class_="text-lg sm:text-2xl lg:text-4xl text-accent font-alien")[
            "TIMETRACKER"
        ],
    ]
    hamburger = Button(
        data_collapse_toggle="navbar-dropdown",
        type="button",
        aria_controls="navbar-dropdown",
        aria_expanded="false",
        class_="inline-flex items-center p-2 w-10 h-10 justify-center text-sm text-gray-500 rounded-lg md:hidden hover:bg-gray-100 focus:outline-hidden focus:ring-2 focus:ring-gray-200 dark:text-gray-400 dark:hover:bg-gray-700 dark:focus:ring-gray-600",
    )[Span(class_="sr-only")["Open main menu"], Icon("hamburger")]

    menu = NavbarMenu(
        today_played=today_played,
        last_7_played=last_7_played,
        today_url=today_url,
        last_7_url=last_7_url,
        current_year=current_year,
        csrf_token=csrf_token,
    )
    return Nav(class_="bg-neutral-primary-soft border-b border-default py-4")[
        Div(
            class_=f"w-full {CONTENT_MAX_WIDTH_CLASS} flex flex-wrap items-center "
            "justify-between mx-auto"
        )[brand, hamburger, menu]
    ]


def TimetrackerDocument(
    content: "Node | SafeText | str",
    *,
    request: HttpRequest,
    title: str = "",
    scripts: "Node | SafeText | str" = "",
    mastered: bool = False,
) -> Document:
    """Assemble a full HTML document around `content` (the fast_app equivalent).

    Scripts are collected from `content`'s component tree: every component
    declares its JS via `Media`, and `collect_media` gathers (deduped) the union
    for the whole page. The `scripts` argument remains for page-specific glue
    that isn't owned by a reusable component (e.g. the add-form helpers).
    """
    from common.components import Media, ModuleScript, StaticScript, collect_media
    from games.views.general import global_current_year, model_counts

    counts = model_counts(request)
    year = global_current_year(request)["global_current_year"]
    navbar = Navbar(
        today_played=counts["today_played"],
        last_7_played=counts["last_7_played"],
        today_url=counts["today_url"],
        last_7_url=counts["last_7_url"],
        current_year=year,
        csrf_token=get_token(request),
    )

    # Collect JS from both the page body and the navbar (the navbar owns the
    # <drop-down> custom element, so its media must be emitted too). The global
    # modal container (below) receives HTMX-swapped confirm modals
    # (<modal-dialog>) on any page, and the swapped-in fragment carries no script
    # of its own — so its dismiss element must be defined page-globally.
    media = (
        collect_media(content)
        + collect_media(navbar)
        + Media(js=("dist/elements/modal-dialog.js",))
    )
    collected_scripts = "".join(
        [str(ModuleScript(name)) for name in media.js]
        + [str(StaticScript(name)) for name in media.js_external]
    )
    all_scripts = collected_scripts + (str(scripts) if scripts else "")

    messages = [
        {"message": str(m.message), "type": (m.tags or "info")}
        for m in get_messages(request)
    ]
    # Embed as JSON; guard against `</script>` breaking out of the tag.
    messages_json = json.dumps(messages).replace("</", "<\\/")

    def html_document(title: str = "") -> Document:
        htmx_indicator = Img(
            id="indicator",
            src=static("icons/loading.png"),
            class_="absolute right-3 top-3 animate-spin htmx-indicator",
            height="24",
            width="24",
            alt="loading indicator",
        )

        version_footer_note = Span(
            class_="fixed left-2 bottom-2 text-xs text-slate-300 dark:text-slate-600"
        )[f"{version()} ({version_date()})"]

        script_body = Safe(all_scripts)
        global_modal_container = Div(id="global-modal-container", hx_swap_oob="true")
        toast_container = Safe(_TOAST_CONTAINER)
        mastered_script_IS_THIS_REALLY_NEEDED = Script(type="module")[
            _main_script(mastered)
        ]
        return Document(
            Html(lang="en")[
                Head()[
                    [
                        Title()[f"Timetracker - {title}"],
                        Meta(charset="utf-8"),
                        Meta(name="description", content="Self-hosted time-tracker."),
                        Meta(
                            name="keywords",
                            content="time, tracking, video games, self-hosted",
                        ),
                        Meta(
                            name="viewport",
                            content="width=device-width, initial-scale=1.0",
                        ),
                        Link(
                            rel="icon",
                            type="image/svg+xml",
                            href=static("icons/tesserae-favicon.svg"),
                        ),
                        ModuleScript("dist/global-error-handler.js"),
                        Script(src=static("js/htmx.min.js")),
                        Script(src=static("js/flowbite.min.js")),
                        ModuleScript("dist/htmx-redirect-toast.js"),
                        ModuleScript("dist/toast.js"),
                        Script(defer=True, src=static("js/alpine-mask.min.js")),
                        Script(defer=True, src=static("js/alpine.min.js")),
                        Script()[
                            "htmx.config.scrollBehavior = 'smooth';\n"
                            "htmx.config.selfRequestsOnly = false;\n"
                        ],
                        Script()[_THEME_FOUC_SCRIPT],
                        Script(id="django-messages", type="application/json")[
                            messages_json
                        ],
                        Safe(str(django_htmx_script(nonce=None))),
                        Link(rel="stylesheet", href=static("base.css")),
                    ]
                ],
                Body(hx_indicator="#indicator", class_="bg-neutral-primary text-body")[
                    htmx_indicator,
                    Div(class_="flex flex-col min-h-screen")[
                        navbar,
                        Div(
                            id="main-container",
                            class_="flex flex-1 flex-col pt-8 pb-16",
                        )[content],
                    ],
                    version_footer_note,
                    script_body,
                    mastered_script_IS_THIS_REALLY_NEEDED,
                    global_modal_container,
                    toast_container,
                ],
            ],
        )

    return html_document(title=title)


def render_page(
    request: HttpRequest,
    content: "Node | SafeText | str",
    *,
    title: str = "",
    scripts: "Node | SafeText | str" = "",
    mastered: bool = False,
    status: int = 200,
) -> HttpResponse:
    """`render()`-style shortcut: build a full page and return an HttpResponse."""
    return HttpResponse(
        TimetrackerDocument(
            content, request=request, title=title, scripts=scripts, mastered=mastered
        ),
        status=status,
    )
