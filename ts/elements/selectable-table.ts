/** <selectable-table> — the personality a data table gains for acting on many
 * rows at once.
 *
 * Selection is a mode: off on every load, turned on by the Select toggle in
 * the footer's selection line. Only then does the element build a checkbox in
 * each row's identity cell, so a page with no scripting renders none. The
 * element holds the selection, announces each change of scope, and publishes
 * the statement as `selectable-table:change` — the field that posts it is
 * #712's.
 */

import { readSelectableTableProps, SelectableTableProps } from "../generated/props.js";

export class SelectableTableElement extends HTMLElement {
  private props!: SelectableTableProps;

  connectedCallback(): void {
    this.props = readSelectableTableProps(this);
  }
}

customElements.define("selectable-table", SelectableTableElement);
