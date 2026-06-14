"""Tests for the configuration reader in ``timetracker/config.py``."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from timetracker import config as config_module
from timetracker.config import config


@pytest.fixture(autouse=True)
def _clear_caches():
    """Each test sees freshly parsed files."""
    config_module.reset_caches()
    yield
    config_module.reset_caches()


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    def _write(contents: str):
        path = tmp_path / ".env"
        path.write_text(contents)
        monkeypatch.setenv("ENV_FILE", str(path))
        config_module.reset_caches()
        return path

    return _write


@pytest.fixture
def ini_file(tmp_path, monkeypatch):
    def _write(contents: str):
        path = tmp_path / "settings.ini"
        path.write_text(contents)
        monkeypatch.setenv("INI_FILE", str(path))
        config_module.reset_caches()
        return path

    return _write


def test_default_returned_when_unset():
    assert config("TOTALLY_UNSET_VALUE", default="fallback") == "fallback"


def test_missing_without_default_raises():
    with pytest.raises(ImproperlyConfigured):
        config("TOTALLY_UNSET_VALUE")


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("SOME_SETTING", "from-env")
    assert config("SOME_SETTING", default="fallback") == "from-env"


def test_priority_env_beats_files(monkeypatch, env_file, ini_file):
    ini_file("[timetracker]\nVALUE = from-ini\n")
    env_file("VALUE=from-dotenv\n")
    monkeypatch.setenv("VALUE", "from-env")
    assert config("VALUE") == "from-env"


def test_priority_dotenv_beats_ini(env_file, ini_file):
    ini_file("[timetracker]\nVALUE = from-ini\n")
    env_file("VALUE=from-dotenv\n")
    assert config("VALUE") == "from-dotenv"


def test_priority_ini_beats_default(ini_file):
    ini_file("[timetracker]\nVALUE = from-ini\n")
    assert config("VALUE", default="fallback") == "from-ini"


def test_ini_preserves_key_case(ini_file):
    ini_file("[timetracker]\nSECRET_KEY = abc\n")
    assert config("SECRET_KEY") == "abc"


# --- __FILE secret pointer -------------------------------------------------


def test_file_pointer_read_and_stripped(tmp_path, monkeypatch):
    secret = tmp_path / "secret"
    secret.write_text("super-secret-value\n")  # trailing newline must be stripped
    monkeypatch.setenv("SECRET_KEY__FILE", str(secret))
    assert config("SECRET_KEY", allow_file=True) == "super-secret-value"


def test_file_pointer_ignored_without_allow_file(tmp_path, monkeypatch):
    secret = tmp_path / "secret"
    secret.write_text("ignored")
    monkeypatch.setenv("SECRET_KEY__FILE", str(secret))
    assert config("SECRET_KEY", default="fallback") == "fallback"


def test_file_pointer_beats_env(tmp_path, monkeypatch):
    secret = tmp_path / "secret"
    secret.write_text("from-file")
    monkeypatch.setenv("SECRET_KEY__FILE", str(secret))
    monkeypatch.setenv("SECRET_KEY", "from-env")
    assert config("SECRET_KEY", allow_file=True) == "from-file"


# --- casting ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("", False),
    ],
)
def test_cast_bool(monkeypatch, raw, expected):
    monkeypatch.setenv("FLAG", raw)
    assert config("FLAG", cast=bool) is expected


def test_cast_list(monkeypatch):
    monkeypatch.setenv("HOSTS", "a.example, b.example , ,c.example")
    assert config("HOSTS", cast=list) == ["a.example", "b.example", "c.example"]


def test_cast_int(monkeypatch):
    monkeypatch.setenv("COUNT", "42")
    assert config("COUNT", cast=int) == 42


def test_cast_not_applied_to_default():
    # A None default passes through untouched even with a cast set.
    assert config("UNSET", default=None, cast=list) is None


# --- required_in_prod ------------------------------------------------------


def test_required_in_prod_raises_when_prod(monkeypatch):
    monkeypatch.setenv("DEBUG", "false")
    with pytest.raises(ImproperlyConfigured):
        config("SECRET_KEY", default="dev-default", required_in_prod=True)


def test_required_in_prod_uses_default_in_debug(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    assert config("SECRET_KEY", default="dev-default", required_in_prod=True) == (
        "dev-default"
    )


def test_deprecated_prod_var_implies_production(monkeypatch):
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.setenv("PROD", "1")
    with pytest.raises(ImproperlyConfigured):
        config("SECRET_KEY", default="dev-default", required_in_prod=True)


# --- .env parser edge cases ------------------------------------------------


def test_env_parser_quotes_comments_and_export(env_file):
    env_file(
        "\n".join(
            [
                "# a comment line",
                "PLAIN=value",
                "export EXPORTED=exported-value",
                'DOUBLE="quoted value"',
                "SINGLE='single quoted'",
                "INLINE=value  # trailing comment",
                'HASH_IN_QUOTES="a # b"',
                "EMPTY=",
                'QUOTED_THEN_COMMENT="keep" # drop',
            ]
        )
        + "\n"
    )
    assert config("PLAIN") == "value"
    assert config("EXPORTED") == "exported-value"
    assert config("DOUBLE") == "quoted value"
    assert config("SINGLE") == "single quoted"
    assert config("INLINE") == "value"
    assert config("HASH_IN_QUOTES") == "a # b"
    assert config("EMPTY", default="x") == ""
    assert config("QUOTED_THEN_COMMENT") == "keep"


def test_missing_files_are_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "does-not-exist.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "does-not-exist.ini"))
    config_module.reset_caches()
    assert config("ANYTHING", default="fallback") == "fallback"
