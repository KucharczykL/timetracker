/**
 * <sort-header> — clickable sortable table header.
 *
 * The server bakes both navigation targets onto the inner <a>: `href` is the
 * plain-click target (sort by this column alone), `data-shift-href` is the
 * shift-click target (add/cycle this column within the existing multi-column
 * sort). All sort math is done server-side; this element only routes a
 * shift-click to the alternate target. Plain click falls through to the native
 * link, so headers still work without JavaScript.
 */
class SortHeaderElement extends HTMLElement {
    connectedCallback(): void {
        const link = this.querySelector("a");
        if (!(link instanceof HTMLAnchorElement)) return;
        if (link.dataset.sortHeaderWired) return;
        link.dataset.sortHeaderWired = "true";

        link.addEventListener("click", (event) => {
            // Leave ctrl/meta/middle-click (open-in-new-tab) alone; only the
            // shift modifier means "add this column to the sort".
            if (!event.shiftKey) return;
            const shiftHref = link.getAttribute("data-shift-href");
            if (!shiftHref) return;
            // Shift-click would otherwise open a new window — take over.
            event.preventDefault();
            window.location.assign(shiftHref);
        });
    }
}

customElements.define("sort-header", SortHeaderElement);
