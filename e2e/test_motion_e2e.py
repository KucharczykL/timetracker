"""Each floating surface enters and leaves, then settles with nothing held."""

from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page, ViewportSize, expect

from e2e.helpers import open_facet

PHONE = ViewportSize(width=390, height=844)
LEAVING = '[data-motion="leaving"]'
SHEET = "dialog[data-dropdown-sheet][open]"
CENTRED_DIALOG = "dialog[data-modal][open]"


def _settled(page: Page) -> None:
    expect(page.locator(LEAVING)).to_have_count(0)


def test_a_desktop_menu_enters_and_leaves_settled(
    motion_page: Page, live_server, e2e_library
):
    page = motion_page
    create_device(e2e_library, "Deck")
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")

    page.get_by_role("button", name="Deck (Unknown) actions").click()
    menu = page.get_by_role("menu")
    expect(menu).to_be_visible()
    expect(page.locator("[data-motion]")).to_have_count(0)

    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    _settled(page)


def test_a_centred_form_dialog_closes_settled(
    motion_page: Page, live_server, e2e_library
):
    page = motion_page
    deck = create_device(e2e_library, "Deck")
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")
    edit = f'a[href^="{reverse("games:edit_device", args=[deck.pk])}"]'
    page.locator(edit).first.evaluate(
        "link => link.setAttribute('data-form-dialog', '')"
    )
    page.get_by_role("button", name="Deck (Unknown) actions").click()
    page.locator(edit).click()
    expect(page.locator(CENTRED_DIALOG)).to_be_visible()

    page.keyboard.press("Escape")
    expect(page.locator(CENTRED_DIALOG)).to_have_count(0)
    _settled(page)


def test_a_bottom_sheet_at_phone_width_closes_settled(motion_page: Page, live_server):
    page = motion_page
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    open_facet(page, "status")
    expect(page.locator(SHEET)).to_be_visible()

    page.keyboard.press("Escape")
    expect(page.locator(SHEET)).to_have_count(0)
    _settled(page)


def test_a_toast_enters_entered(motion_page: Page, live_server):
    page = motion_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    page.evaluate("window.toast('Saved')")
    expect(page.locator("toast-stack [data-entered]").first).to_be_attached()
    _settled(page)
