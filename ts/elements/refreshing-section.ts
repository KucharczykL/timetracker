/** <refreshing-section> — a part of the page that reads itself again.
 *
 * When the named event reaches the body, the element reads the page
 * again and takes the children of the element with its own id from the
 * answer. The Game detail History section refreshes this way after a
 * status change.
 */
import { reportClientError } from "../client-errors.js";
import { readRefreshingSectionProps } from "../generated/props.js";

/** The children of the element with this id in a page's HTML, or null. */
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
