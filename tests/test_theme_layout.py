from django.test import Client
from django.urls import reverse


def test_login_layout_uses_isolated_prepaint_bootstrap_and_theme_component(db):
    html = Client().get(reverse("login")).content.decode()

    assert 'id="theme-bootstrap"' in html
    assert html.index('id="theme-bootstrap"') < html.index('href="/static/base.css"')
    assert "<theme-toggle" in html
    assert 'data-theme-icon="auto"' in html
    assert 'data-theme-icon="light"' in html
    assert 'data-theme-icon="dark"' in html
    assert "dist/elements/theme-toggle.js" in html


def test_layout_removes_legacy_inline_navbar_theme_handler(db):
    html = Client().get(reverse("login")).content.decode()

    assert "themeToggleBtn.addEventListener" not in html
    assert "localStorage.getItem('color-theme')" not in html


def test_prepaint_bootstrap_checks_migration_cookie_then_cookie_then_storage(db):
    html = Client().get(reverse("login")).content.decode()
    bootstrap = html[
        html.index('id="theme-bootstrap"') : html.index(
            "</script>", html.index('id="theme-bootstrap"')
        )
    ]

    assert bootstrap.index('readCookie("color-theme-migrate")') < bootstrap.index(
        'readCookie("color-theme")'
    )
    assert bootstrap.index("document.cookie") < bootstrap.index("localStorage")
    assert "prefers-color-scheme: dark" in bootstrap
