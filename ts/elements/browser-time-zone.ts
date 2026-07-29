import { readBrowserTimeZoneProps } from "../generated/props.js";

// Stamps the browser's IANA zone into a hidden input so a plain form POST can
// record where the user actually was. The value is data, not presentation: the
// account display zone is a preference and would misreport a travelling user,
// which is the whole reason each timestamp carries its own zone.
//
// Server-side the value is validated and an unusable name is ignored, so a
// browser whose zone this runtime cannot resolve degrades to an unlabelled
// endpoint rather than a failed save.
class BrowserTimeZoneElement extends HTMLElement {
  connectedCallback(): void {
    const props = readBrowserTimeZoneProps(this);
    const input = this.querySelector<HTMLInputElement>(
      `input[name="${props.fieldName}"]`,
    );
    if (!input) return;
    input.value = Intl.DateTimeFormat().resolvedOptions().timeZone;
  }
}

customElements.define("browser-time-zone", BrowserTimeZoneElement);
