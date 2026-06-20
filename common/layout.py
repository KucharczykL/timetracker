"""A small fast_app-style layout system.

Instead of Django template inheritance (`{% extends "base.html" %}`), views
build their page body with Python components and wrap it with `Page()` /
`render_page()`. `Page()` is the equivalent of FastHTML's document wrapper:
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
from django.utils.html import conditional_escape
from django.utils.safestring import SafeText, mark_safe
from django_htmx.jinja import django_htmx_script

from games.templatetags.version import version, version_date

if TYPE_CHECKING:
    from common.components import Node

# Static head script that sets the dark/light class before paint (avoids FOUC).
_THEME_FOUC_SCRIPT = """<script>
            if (localStorage.getItem('color-theme') === 'dark' || (!('color-theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
                document.documentElement.classList.add('dark');
            } else {
                document.documentElement.classList.remove('dark')
            }
        </script>"""

# The main module script: crown icon mount + theme-toggle wiring.
# Split around the single dynamic value (game.mastered).
_MAIN_SCRIPT_A = """<script type="module">
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
        </script>"""

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
    today_played: str, last_7_played: str, *, oob: bool = False
) -> "Node":
    """The navbar 'Today · Last 7 days' totals. Carries a stable id so
    htmx endpoints can refresh it out-of-band after a session change."""
    from common.components import Safe

    oob_attr = ' hx-swap-oob="true"' if oob else ""
    return Safe(
        f'<li id="navbar-playtime"{oob_attr} '
        'class="dark:text-white flex flex-col items-center text-xs">'
        '<span class="flex uppercase gap-1">Today'
        '<span class="dark:text-gray-400">·</span>Last 7 days</span>'
        '<span class="flex items-center gap-1">'
        f'{today_played}<span class="dark:text-gray-400">·</span>'
        f"{last_7_played}</span></li>"
    )


def Navbar(
    *, today_played: str, last_7_played: str, current_year: int, csrf_token: str
) -> "Node":
    """Top navigation bar.

    Static chrome, so it's a single ``Safe`` node wrapping its markup rather
    than a hand-built element tree — trusted HTML belongs in a ``Safe`` node,
    not a ``mark_safe`` string."""
    from common.components import Safe

    logo = static("icons/schedule.png")
    return Safe(f"""<nav class="bg-neutral-primary-soft border-b border-default">
    <div class="max-w-(--breakpoint-xl) flex flex-wrap items-center justify-between mx-auto p-4">
        <a href="{reverse("games:index")}"
           class="flex items-center space-x-3 rtl:space-x-reverse">
            <img src="{logo}" height="48" width="48" alt="Timetracker Logo" class="mr-4" />
            <span class="self-center text-2xl font-semibold whitespace-nowrap dark:text-white">Timetracker</span>
        </a>
        <button data-collapse-toggle="navbar-dropdown" type="button"
                class="inline-flex items-center p-2 w-10 h-10 justify-center text-sm text-gray-500 rounded-lg md:hidden hover:bg-gray-100 focus:outline-hidden focus:ring-2 focus:ring-gray-200 dark:text-gray-400 dark:hover:bg-gray-700 dark:focus:ring-gray-600"
                aria-controls="navbar-dropdown" aria-expanded="false">
            <span class="sr-only">Open main menu</span>
            <svg class="w-5 h-5" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 17 14">
                <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M1 1h15M1 7h15M1 13h15" />
            </svg>
        </button>
        <div class="hidden w-full md:block md:w-auto" id="navbar-dropdown">
            <ul class="items-center flex flex-col font-medium p-4 md:p-0 mt-4 border border-gray-100 rounded-lg bg-gray-50 md:space-x-8 rtl:space-x-reverse md:flex-row md:mt-0 md:border-0 md:bg-white dark:bg-gray-800 md:dark:bg-gray-900 dark:border-gray-700">
                <li class="flex items-center">
                    <button id="theme-toggle" type="button" class="p-2 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 focus:outline-hidden focus:ring-4 focus:ring-gray-200 dark:focus:ring-gray-700 rounded-lg text-sm hover:cursor-pointer">
                        <svg id="theme-toggle-dark-icon" class="hidden w-5 h-5" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path d="M3.32031 11.6835C3.32031 16.6541 7.34975 20.6835 12.3203 20.6835C16.1075 20.6835 19.3483 18.3443 20.6768 15.032C19.6402 15.4486 18.5059 15.6834 17.3203 15.6834C12.3497 15.6834 8.32031 11.654 8.32031 6.68342C8.32031 5.50338 8.55165 4.36259 8.96453 3.32996C5.65605 4.66028 3.32031 7.89912 3.32031 11.6835Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        <svg id="theme-toggle-light-icon" class="hidden w-5 h-5" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                        <path d="M12 3V4M12 20V21M4 12H3M6.31412 6.31412L5.5 5.5M17.6859 6.31412L18.5 5.5M6.31412 17.69L5.5 18.5001M17.6859 17.69L18.5 18.5001M21 12H20M16 12C16 14.2091 14.2091 16 12 16C9.79086 16 8 14.2091 8 12C8 9.79086 9.79086 8 12 8C14.2091 8 16 9.79086 16 12Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                    </button>
                </li>
                {NavbarPlaytime(today_played, last_7_played)}
                <li>
                    <a href="#" class="block py-2 px-3 text-white bg-blue-700 rounded-sm md:bg-transparent md:text-blue-700 md:p-0 md:dark:text-blue-500 dark:bg-blue-600 md:dark:bg-transparent" aria-current="page">Home</a>
                </li>
                <li>
                    <button id="dropdownNavbarNewLink" data-dropdown-toggle="dropdownNavbarNew"
                            class="flex items-center justify-between w-full py-2 px-3 text-gray-900 rounded-sm hover:bg-gray-100 md:hover:bg-transparent md:border-0 md:hover:text-blue-700 md:p-0 md:w-auto dark:text-white md:dark:hover:text-blue-500 dark:focus:text-white dark:border-gray-700 dark:hover:bg-gray-700 md:dark:hover:bg-transparent hover:cursor-pointer">
                        New
                        <svg class="w-2.5 h-2.5 ms-2.5" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 10 6">
                            <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 4 4 4-4" />
                        </svg>
                    </button>
                    <div id="dropdownNavbarNew" class="z-10 hidden font-normal bg-white divide-y divide-gray-100 rounded-lg shadow-sm w-44 dark:bg-gray-700 dark:divide-gray-600">
                        <ul class="py-2 text-sm text-gray-700 dark:text-gray-400" aria-labelledby="dropdownLargeButton">
                            <li><a href="{reverse("games:add_device")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Device</a></li>
                            <li><a href="{reverse("games:add_game")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Game</a></li>
                            <li><a href="{reverse("games:add_platform")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Platform</a></li>
                            <li><a href="{reverse("games:add_purchase")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Purchase</a></li>
                            <li><a href="{reverse("games:add_session")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Session</a></li>
                        </ul>
                    </div>
                </li>
                <li>
                    <button id="dropdownNavbarManageLink" data-dropdown-toggle="dropdownNavbarManage"
                            class="flex items-center justify-between w-full py-2 px-3 text-gray-900 rounded-sm hover:bg-gray-100 md:hover:bg-transparent md:border-0 md:hover:text-blue-700 md:p-0 md:w-auto dark:text-white md:dark:hover:text-blue-500 dark:focus:text-white dark:border-gray-700 dark:hover:bg-gray-700 md:dark:hover:bg-transparent hover:cursor-pointer">
                        Manage
                        <svg class="w-2.5 h-2.5 ms-2.5" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 10 6">
                            <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 4 4 4-4" />
                        </svg>
                    </button>
                    <div id="dropdownNavbarManage" class="z-10 hidden font-normal bg-white divide-y divide-gray-100 rounded-lg shadow-sm w-44 dark:bg-gray-700 dark:divide-gray-600">
                        <ul class="py-2 text-sm text-gray-700 dark:text-gray-400" aria-labelledby="dropdownLargeButton">
                            <li><a href="{reverse("games:list_devices")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Devices</a></li>
                            <li><a href="{reverse("games:list_games")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Games</a></li>
                            <li><a href="{reverse("games:list_platforms")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Platforms</a></li>
                            <li><a href="{reverse("games:list_playevents")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Play events</a></li>
                            <li><a href="{reverse("games:list_purchases")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Purchases</a></li>
                            <li><a href="{reverse("games:list_sessions")}" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white">Sessions</a></li>
                        </ul>
                    </div>
                </li>
                <li>
                    <a href="{reverse("games:stats_by_year", args=[current_year])}" class="block py-2 px-3 text-gray-900 rounded-sm hover:bg-gray-100 md:hover:bg-transparent md:border-0 md:hover:text-blue-700 md:p-0 dark:text-white md:dark:hover:text-blue-500 dark:hover:bg-gray-700 dark:hover:text-white md:dark:hover:bg-transparent">Stats</a>
                </li>
                <li>
                    <form method="post" action="{reverse("logout")}">
                        <input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">
                        <button type="submit" class="block py-2 px-3 text-gray-900 rounded-sm hover:bg-gray-100 md:hover:bg-transparent md:border-0 md:hover:text-blue-700 md:p-0 dark:text-white md:dark:hover:text-blue-500 dark:hover:bg-gray-700 dark:hover:text-white md:dark:hover:bg-transparent">Log out</button>
                    </form>
                </li>
            </ul>
        </div>
    </div>
</nav>""")


def Page(
    content: "Node | SafeText | str",
    *,
    request: HttpRequest,
    title: str = "",
    scripts: "Node | SafeText | str" = "",
    mastered: bool = False,
) -> SafeText:
    """Assemble a full HTML document around `content` (the fast_app equivalent).

    Scripts are collected from `content`'s component tree: every component
    declares its JS via `Media`, and `collect_media` gathers (deduped) the union
    for the whole page. The `scripts` argument remains for page-specific glue
    that isn't owned by a reusable component (e.g. the add-form helpers).
    """
    from common.components import ModuleScript, StaticScript, collect_media
    from games.views.general import global_current_year, model_counts

    media = collect_media(content)
    collected_scripts = "".join(
        [str(ModuleScript(name)) for name in media.js]
        + [str(StaticScript(name)) for name in media.js_external]
    )
    all_scripts = collected_scripts + (str(scripts) if scripts else "")

    counts = model_counts(request)
    year = global_current_year(request)["global_current_year"]
    navbar = Navbar(
        today_played=counts["today_played"],
        last_7_played=counts["last_7_played"],
        current_year=year,
        csrf_token=get_token(request),
    )

    messages = [
        {"message": str(m.message), "type": (m.tags or "info")}
        for m in get_messages(request)
    ]
    # Embed as JSON; guard against `</script>` breaking out of the tag.
    messages_json = json.dumps(messages).replace("</", "<\\/")

    head = (
        '<!DOCTYPE html>\n<html lang="en">\n    <head>\n'
        '        <meta charset="utf-8" />\n'
        '        <meta name="description" content="Self-hosted time-tracker." />\n'
        '        <meta name="keywords" content="time, tracking, video games, self-hosted" />\n'
        '        <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"        <title>Timetracker - {conditional_escape(title)}</title>\n"
        f'        <script src="{static("js/htmx.min.js")}"></script>\n'
        "        <script>\n"
        "            htmx.config.scrollBehavior = 'smooth';\n"
        "            htmx.config.selfRequestsOnly = false;\n"
        "        </script>\n"
        f'        <script src="{static("js/dist/htmx-redirect-toast.js")}"></script>\n'
        f"        {django_htmx_script(nonce=None)}\n"
        f'        <link rel="stylesheet" href="{static("base.css")}" />\n'
        # Vendored bundles (flowbite 2.4.1, alpinejs/@alpinejs/mask 3.15.12) —
        # served locally so pages work offline (and in browser tests). The mask
        # plugin must load before Alpine core; both stay deferred.
        f'        <script src="{static("js/flowbite.min.js")}"></script>\n'
        f'        <script defer src="{static("js/alpine-mask.min.js")}"></script>\n'
        f'        <script defer src="{static("js/alpine.min.js")}"></script>\n'
        f"        {_THEME_FOUC_SCRIPT}\n"
        "    </head>\n"
    )

    body = (
        '    <body hx-indicator="#indicator" class="bg-neutral-primary">\n'
        f'        <script id="django-messages" type="application/json">{messages_json}</script>\n'
        f'        <img id="indicator" src="{static("icons/loading.png")}" class="absolute right-3 top-3 animate-spin htmx-indicator" height="24" width="24" alt="loading indicator" />\n'
        '        <div class="flex flex-col min-h-screen">\n'
        f"            {navbar}\n"
        f'            <div id="main-container" class="flex flex-1 flex-col pt-8 pb-16">{content}</div>\n'
        f'            <span class="fixed left-2 bottom-2 text-xs text-slate-300 dark:text-slate-600">{version()} ({version_date()})</span>\n'
        "        </div>\n"
        f"        {all_scripts}\n"
        f"        {_main_script(mastered)}\n"
        "        <!-- hx-swap-oob makes sure the modal gets removed upon any HTMX response -->\n"
        '        <div id="global-modal-container" hx-swap-oob="true"></div>\n'
        f"        {_TOAST_CONTAINER}\n"
        f'        <script src="{static("js/dist/toast.js")}"></script>\n'
        "    </body>\n</html>\n"
    )

    return mark_safe(head + body)


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
        Page(content, request=request, title=title, scripts=scripts, mastered=mastered),
        status=status,
    )
