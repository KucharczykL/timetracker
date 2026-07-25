"""Serializes current SiteSetting DB rows to a settings.ini snapshot (issue #392).

Read-only / pure: builds text, does not touch the filesystem. The caller (the
admin-settings export view) decides how to deliver it.
"""

import io
from configparser import ConfigParser

from timetracker.config import INI_SECTION


def export_site_settings_ini() -> str:
    """Render every stored ``SiteSetting`` row as a ``[timetracker]`` ini section.

    Exports every DB row verbatim, including one for a key no longer in the
    settings registry (a stale row from a removed/renamed setting) — the
    reader loads the whole section into a plain dict, so an unknown key is
    inert on re-import, and silently dropping a real stored value would make
    this an incomplete backup.

    Matches the reader in ``timetracker/config.py`` (``_load_ini_file`` /
    ``dict(parser[INI_SECTION])``, read under the default ``BasicInterpolation``):
    values are written unquoted (only ``.env`` reading strips quotes; ``.ini``
    reading does not) and any literal ``%`` is doubled so interpolation on
    read collapses it back to one ``%`` instead of raising. Leading/trailing
    whitespace in a value does not survive the round trip — an inherent ini
    limitation (``ConfigParser`` strips it on read), not something this
    function preserves.
    """
    from games.models import SiteSetting

    parser = ConfigParser()
    # Preserve key case; ConfigParser lowercases option names by default, and
    # the reader also sets this so the two sides agree on key spelling.
    parser.optionxform = str  # type: ignore[assignment, method-assign]
    parser.add_section(INI_SECTION)

    for row in SiteSetting.objects.order_by("key"):
        raw_value = str(row.value).replace("%", "%%")
        parser.set(INI_SECTION, row.key, raw_value)

    buffer = io.StringIO()
    parser.write(buffer)
    return buffer.getvalue()


__all__ = ["export_site_settings_ini"]
