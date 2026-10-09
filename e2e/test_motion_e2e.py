"""Floating surfaces enter and leave cleanly."""

from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page, ViewportSize, expect

from e2e.helpers import close_sheets, open_facet, record_copy, top_sheet

PHONE = ViewportSize(width=390, height=844)
LEAVING = '[data-motion="leaving"]'
SHEET = "dialog[data-dropdown-sheet][open]"
CENTRED_DIALOG = "dialog[data-modal][open]"
LEVEL = "dialog[data-dropdown-sheet][data-sheet-level][open]"


SAMPLE_FRAMES = 90


def _settled(page: Page) -> None:
    expect(page.locator(LEAVING)).to_have_count(0)


def _watch(page: Page, attribute: str) -> None:
    """Record each change to the attribute, with the animations live at it."""
    page.evaluate(
        """(attribute) => {
            const records = (window.__motion = []);
            new MutationObserver((mutations) => {
                for (const mutation of mutations) {
                    const node = mutation.target;
                    records.push({
                        from: mutation.oldValue,
                        to: node.getAttribute(attribute),
                        animations: node.getAnimations({ subtree: true }).length,
                    });
                }
            }).observe(document.body, {
                subtree: true,
                attributes: true,
                attributeFilter: [attribute],
                attributeOldValue: true,
            });
        }""",
        attribute,
    )


def _assert_animated(page: Page, value: str) -> None:
    """Some change to the value ran a live animation."""
    records = page.evaluate("window.__motion")
    touched = [record for record in records if value in (record["from"], record["to"])]
    assert touched, records
    assert any(record["animations"] > 0 for record in touched), records


def test_a_desktop_menu_enters_and_leaves_settled(
    motion_page: Page, live_server, e2e_library
):
    page = motion_page
    create_device(e2e_library, "Deck")
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")

    _watch(page, "data-motion")
    page.get_by_role("button", name="Deck (Unknown) actions").click()
    menu = page.get_by_role("menu")
    expect(menu).to_be_visible()
    _assert_animated(page, "entering")
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
    page.get_by_role("button", name="Deck (Unknown) actions").click()
    page.locator(edit).click()
    expect(page.locator(CENTRED_DIALOG)).to_be_visible()

    _watch(page, "data-motion")
    page.keyboard.press("Escape")
    expect(page.locator(CENTRED_DIALOG)).to_have_count(0)
    _assert_animated(page, "leaving")
    _settled(page)


def test_a_bottom_sheet_at_phone_width_closes_settled(motion_page: Page, live_server):
    page = motion_page
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    open_facet(page, "status")
    expect(top_sheet(page)).to_be_visible()

    # Escape closes the one open sheet.
    _watch(page, "data-motion")
    close_sheets(page)
    expect(page.locator(SHEET)).to_have_count(0)
    _assert_animated(page, "leaving")
    _settled(page)


def test_a_toast_enters_entered(motion_page: Page, live_server):
    page = motion_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    _watch(page, "data-entered")
    page.evaluate("window.toast('Saved')")
    expect(page.locator("toast-stack [data-entered]").first).to_be_attached()
    _assert_animated(page, "")
    _settled(page)


def test_a_sheet_level_pushes_in_and_backs_out_settled(
    motion_page: Page, live_server, e2e_user, e2e_library
):
    page = motion_page
    page.set_viewport_size(PHONE)
    record_copy(e2e_user, e2e_library, "Tunic")
    page.goto(f"{live_server.url}{reverse('games:list_library')}")

    page.get_by_role("button", name="Tunic (PS5) actions").click()
    item = page.locator(SHEET).get_by_role("menuitem", name="I no longer have it")
    _sample_level(page)
    item.evaluate("item => item.click()")
    expect(page.locator(LEVEL)).to_be_visible()
    _settled(page)
    pushed = _sampled_levels(page)
    lefts = [sample["left"] for sample in pushed]
    assert lefts, "the level was never sampled"
    assert any(0 < left < PHONE["width"] for left in lefts), lefts
    assert lefts[-1] == 0, lefts
    assert any(sample["animating"] > 0 for sample in pushed), pushed

    _sample_level(page)
    page.keyboard.press("Escape")
    expect(page.locator(LEVEL)).to_have_count(0)
    _settled(page)
    popped = _sampled_levels(page)
    lefts = [sample["left"] for sample in popped]
    assert lefts, "the level was never sampled on pop"
    assert any(0 < left < PHONE["width"] for left in lefts), lefts
    assert lefts == sorted(lefts), lefts
    assert any(sample["animating"] > 0 for sample in popped), popped


def _sample_level(page: Page) -> None:
    """Sample the level's left edge and live animations, frame by frame, from now on."""
    page.evaluate(
        """(frames) => {
            const token = (window.__levelToken = {});
            const samples = (window.__levelSamples = []);
            window.__levelDone = false;
            let frame = 0;
            const step = () => {
                if (window.__levelToken !== token) return;
                const panel = document.querySelector(
                    "dialog[data-dropdown-sheet][data-sheet-level][open] [data-sheet-panel]",
                );
                if (panel) {
                    samples.push({
                        left: Math.round(panel.getBoundingClientRect().left),
                        animating: document.getAnimations().length,
                    });
                }
                frame += 1;
                if (frame < frames) requestAnimationFrame(step);
                else window.__levelDone = true;
            };
            requestAnimationFrame(step);
        }""",
        SAMPLE_FRAMES,
    )


def _sampled_levels(page: Page) -> list[dict]:
    """Waits out the sampling, then reads it."""
    page.wait_for_function("() => window.__levelDone === true")
    return page.evaluate("window.__levelSamples")
