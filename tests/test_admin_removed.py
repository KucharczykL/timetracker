import json
import os
import subprocess
import sys
from functools import cache


@cache
def _debug_configuration() -> dict[str, object]:
    environment = os.environ.copy()
    environment["DEBUG"] = "true"
    environment.pop("PROD", None)
    script = """
import json
import django

django.setup()

from django.conf import settings
from django.urls import Resolver404, resolve


def resolved_namespace(path):
    try:
        return resolve(path).namespace
    except Resolver404:
        return None


try:
    resolve("/admin/")
except Resolver404:
    admin_route_raises_resolver404 = True
else:
    admin_route_raises_resolver404 = False


print(json.dumps({
    "debug": settings.DEBUG,
    "installed_apps": settings.INSTALLED_APPS,
    "middleware": settings.MIDDLEWARE,
    "admin_route_raises_resolver404": admin_route_raises_resolver404,
    "debug_namespace": resolved_namespace("/__debug__/render_panel/"),
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return json.loads(result.stdout)


def test_debug_configuration_excludes_admin_and_retains_development_tools():
    configuration = _debug_configuration()

    assert configuration["debug"] is True
    assert "django.contrib.admin" not in configuration["installed_apps"]
    assert "django_extensions" in configuration["installed_apps"]
    assert "debug_toolbar" in configuration["installed_apps"]
    assert (
        "debug_toolbar.middleware.DebugToolbarMiddleware" in configuration["middleware"]
    )


def test_debug_urls_exclude_admin_and_retain_debug_toolbar():
    configuration = _debug_configuration()

    assert configuration["admin_route_raises_resolver404"] is True
    assert configuration["debug_namespace"] == "djdt"
