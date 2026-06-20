from common.layout import NavbarPlaytime


def test_navbar_playtime_has_stable_id_and_values():
    html = str(NavbarPlaytime("1 h 00 m", "7 h 00 m"))
    assert 'id="navbar-playtime"' in html
    assert "1 h 00 m" in html
    assert "7 h 00 m" in html
    assert "hx-swap-oob" not in html


def test_navbar_playtime_oob_flag():
    html = str(NavbarPlaytime("1 h 00 m", "7 h 00 m", oob=True))
    assert 'id="navbar-playtime"' in html
    assert 'hx-swap-oob="true"' in html
