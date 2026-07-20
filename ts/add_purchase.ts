import { disableElementsWhenTrue, onSwap } from "./utils.js";
import type {
  SearchSelectChangeDetail,
  SearchSelectElement,
} from "./elements/search-select.js";

// Switch between a single bundle price and one price per game. The per-game
// inputs are the selection-fields element; this only sets the policy: the
// hidden pricing_mode the view reads, the element's "active" flag, and whether
// the bundle Price field is shown.
function applyPricingMode(separate: boolean): void {
  const pricingMode = document.querySelector<HTMLInputElement>("#id_pricing_mode");
  if (pricingMode) pricingMode.value = separate ? "per_game" : "combined";

  const selectionFields = document.querySelector("selection-fields");
  if (selectionFields)
    selectionFields.setAttribute("active", separate ? "true" : "false");

  const priceInput = document.querySelector<HTMLInputElement>("#id_price");
  if (priceInput) {
    const wrapper = priceInput.closest("div");
    if (wrapper) wrapper.classList.toggle("hidden", separate);
  }
}

// ── Related-game auto-fill ──
// For add-on types (DLC / Season Pass / Battle Pass) the Related game is
// almost always the game already picked under Games, so re-selecting it was
// pure double-entry. The auto-fill follows the Games selection while the field
// is empty or still holds a previous auto-fill; a value the user picked
// themselves (or the edit form's server-rendered value) is never overwritten.
// setSelected does not fire search-select:change, so only user picks reach the
// related_game branch of the change listener below.
let autofilledRelatedGameValue: string | null = null;

interface SelectedGame {
  value: string;
  label: string;
}

function firstSelectedGame(): SelectedGame | null {
  const pill = document.querySelector<HTMLElement>(
    'search-select[name="games"] [data-search-select-pills] [data-pill]'
  );
  const value = pill?.getAttribute("data-value");
  if (!pill || !value) return null;
  // textContent picks up markup whitespace around the label text — trim it so
  // the committed label matches what a manual pick of the same game shows.
  const label =
    pill.querySelector("[data-search-select-label]")?.textContent?.trim() || value;
  return { value, label };
}

function syncRelatedGameFromSelection(): void {
  const relatedGameSelect = document.querySelector<SearchSelectElement>(
    'search-select[name="related_game"]'
  );
  if (!relatedGameSelect) return;
  const currentValue =
    relatedGameSelect.querySelector<HTMLInputElement>(
      '[data-search-select-pills] input[type="hidden"]'
    )?.value ?? "";
  if (currentValue && currentValue !== autofilledRelatedGameValue) return;
  // A non-empty box without a committed value is a query the user is typing
  // (editing a committed pick clears it): the field is theirs — never
  // auto-fill over their text. An emptied box hands the field back.
  const searchBoxText =
    relatedGameSelect.querySelector<HTMLInputElement>("[data-search-select-search]")
      ?.value ?? "";
  if (!currentValue && searchBoxText !== "") return;

  const typeSelect = document.querySelector<HTMLSelectElement>("#id_type");
  const isAddonType = typeSelect !== null && typeSelect.value !== "game";
  const game = isAddonType ? firstSelectedGame() : null;
  if (!game) {
    // No game to anchor to (or type switched back to plain "game"): drop a
    // stale auto-fill so its hidden input cannot submit, but keep a user pick.
    if (currentValue) {
      relatedGameSelect.clearSelection();
      autofilledRelatedGameValue = null;
    }
    return;
  }
  if (game.value !== currentValue) {
    relatedGameSelect.setSelected(game.value, game.label);
    autofilledRelatedGameValue = game.value;
  }
}

// The games field is a SearchSelect widget (a <div>, not a <select>), so we
// react to its custom "search-select:change" event instead of syncing a select.
document.addEventListener("search-select:change", (event) => {
  const detail = (event as CustomEvent<SearchSelectChangeDetail>).detail;
  if (detail.name === "related_game") {
    // A user-driven change: from here on the field belongs to the user.
    autofilledRelatedGameValue = null;
    return;
  }
  if (detail.name !== "games") return;

  // Auto-fill platform from the clicked option's data. The platform field is a
  // SearchSelect (#id_platform is its inner search box), so the selection must
  // go through the widget's setSelected — writing the raw input value would
  // display the ID and submit no hidden value (issue #259).
  const last = detail.last;
  const platformId = last && last.data ? last.data.platform : "";
  if (last && platformId) {
    const platformSelect = document.querySelector<SearchSelectElement>(
      'search-select[name="platform"]'
    );
    if (!platformSelect) {
      // The purchase forms always render a platform SearchSelect; a miss means
      // the form structure regressed. Warn instead of silently skipping.
      console.warn("[add_purchase] platform search-select not found; autofill skipped");
    } else {
      if (!last.data.platform_name) {
        // Only reachable under version skew (stale JS vs old API): the hidden
        // value still submits correctly, but the visible label degrades to the id.
        console.warn(
          "[add_purchase] game option missing platform_name; showing id as label",
          last
        );
      }
      platformSelect.setSelected(
        String(platformId),
        String(last.data.platform_name || platformId)
      );
    }
  }

  // The combined/per-game choice is only meaningful with 2+ games. Reveal the
  // checkbox there; below the threshold, fall back to a single bundle price.
  const separateRow = document.querySelector<HTMLElement>("#separate-prices-row");
  const multipleGames = detail.values.length >= 2;
  if (separateRow) separateRow.classList.toggle("hidden", !multipleGames);
  if (!multipleGames) {
    const checkbox = document.querySelector<HTMLInputElement>("#id_separate_prices");
    if (checkbox) checkbox.checked = false;
    applyPricingMode(false);
  }

  syncRelatedGameFromSelection();
});

onSwap("#id_separate_prices", (checkbox) => {
  checkbox.addEventListener("change", () =>
    applyPricingMode((checkbox as HTMLInputElement).checked)
  );
});

function setupElementHandlers(): void {
  disableElementsWhenTrue("#id_type", "game", ["#id_name", "#id_related_game"]);
}

onSwap("#id_type", (typeSelect) => {
  setupElementHandlers();
  typeSelect.addEventListener("change", () => {
    setupElementHandlers();
    syncRelatedGameFromSelection();
  });
});
