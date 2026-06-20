import { readSelectionFieldsProps, SelectionFieldsProps } from "../generated/props.js";

/**
 * Renders one form field per selected item of a source SearchSelect (matched by
 * its name attribute). Reacts to the SearchSelect's "search-select:change" event and
 * to its own "active" attribute. Typed values are preserved (keyed by item id)
 * across selection changes and active toggling.
 */
class SelectionFieldsElement extends HTMLElement {
  static get observedAttributes(): string[] {
    return ["active"];
  }

  private props!: SelectionFieldsProps;
  private source: HTMLElement | null = null;
  private typedValues = new Map<string, string>();

  private readonly onSourceChange = (event: Event): void => {
    const detail = (event as CustomEvent).detail;
    if (!detail || detail.name !== this.props.source) return;
    this.render();
  };

  connectedCallback(): void {
    this.props = readSelectionFieldsProps(this);
    this.source = document.querySelector<HTMLElement>(
      `search-select[name="${this.props.source}"]`,
    );
    document.addEventListener("search-select:change", this.onSourceChange);
    this.render();
  }

  disconnectedCallback(): void {
    document.removeEventListener("search-select:change", this.onSourceChange);
  }

  attributeChangedCallback(): void {
    // connectedCallback assigns props; ignore the initial pre-connect call.
    if (this.props) this.render();
  }

  private selectedItems(): { value: string; label: string }[] {
    if (!this.source) return [];
    const pills = this.source.querySelectorAll(
      "[data-search-select-pills] [data-pill]",
    );
    const items: { value: string; label: string }[] = [];
    pills.forEach((pill) => {
      const value = pill.getAttribute("data-value");
      if (!value) return;
      const labelElement = pill.querySelector("[data-search-select-label]");
      const label = labelElement?.textContent?.trim() || value;
      items.push({ value, label });
    });
    return items;
  }

  private captureTypedValues(): void {
    this.querySelectorAll<HTMLInputElement>(
      "[data-selection-fields-rows] input",
    ).forEach((input) => {
      const itemId = input.getAttribute("data-item-id");
      if (itemId) this.typedValues.set(itemId, input.value);
    });
  }

  private render(): void {
    const rows = this.querySelector<HTMLElement>("[data-selection-fields-rows]");
    const template = this.querySelector<HTMLTemplateElement>(
      "template[data-selection-fields-row]",
    );
    if (!rows || !template) return;

    this.captureTypedValues();
    rows.replaceChildren();

    const active = this.getAttribute("active") === "true";
    const items = this.selectedItems();
    if (!active || items.length < this.props.minItems) return;

    const prototype = template.content.firstElementChild;
    if (!prototype) return;

    items.forEach(({ value, label }) => {
      const row = prototype.cloneNode(true) as HTMLElement;
      const labelElement = row.querySelector("[data-selection-fields-label]");
      const input = row.querySelector<HTMLInputElement>("input");
      if (labelElement) labelElement.textContent = label;
      if (input) {
        input.name = `${this.props.namePrefix}${value}`;
        input.setAttribute("data-item-id", value);
        const preserved = this.typedValues.get(value);
        if (preserved !== undefined) input.value = preserved;
      }
      rows.appendChild(row);
    });
  }
}

customElements.define("selection-fields", SelectionFieldsElement);
