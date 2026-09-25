/** On its event, re-reads its own id's children. */
import { reportClientError } from "../client-errors.js";
import { readRefreshingSectionProps } from "../generated/props.js";

/** Children of `id` in `html`, or null. */
export function sectionFrom(html: string, id: string): Node[] | null {
  const page = new DOMParser().parseFromString(html, "text/html");
  const section = page.getElementById(id);
  return section === null ? null : Array.from(section.childNodes);
}

class RefreshingSectionElement extends HTMLElement {
  private event = "";

  connectedCallback(): void {
    this.event = readRefreshingSectionProps(this).event;
    if (this.event) document.body.addEventListener(this.event, this.onEvent);
  }

  disconnectedCallback(): void {
    if (this.event) document.body.removeEventListener(this.event, this.onEvent);
  }

  private readonly onEvent = (): void => {
    void this.refresh();
  };

  private async refresh(): Promise<void> {
    try {
      const response = await fetch(window.location.href, {
        headers: { Accept: "text/html" },
      });
      if (!response.ok) throw new Error(`GET → ${response.status}`);
      const children = sectionFrom(await response.text(), this.id);
      if (children === null) throw new Error(`no #${this.id} in the answer`);
      this.replaceChildren(...children);
    } catch (error) {
      reportClientError(
        "refreshing-section",
        String((error as Error)?.message ?? error),
        { toast: false },
      );
    }
  }
}

customElements.define("refreshing-section", RefreshingSectionElement);
