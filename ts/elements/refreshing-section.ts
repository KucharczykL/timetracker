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
  //: Next refresh aborts it; answers never cross.
  private abortController: AbortController | null = null;

  connectedCallback(): void {
    this.event = readRefreshingSectionProps(this).event;
    if (this.event) document.body.addEventListener(this.event, this.onEvent);
  }

  disconnectedCallback(): void {
    if (this.event) document.body.removeEventListener(this.event, this.onEvent);
    this.abortController?.abort();
    this.abortController = null;
  }

  private readonly onEvent = (): void => {
    void this.refresh();
  };

  private async refresh(): Promise<void> {
    this.abortController?.abort();
    const controller = new AbortController();
    this.abortController = controller;
    const url = window.location.href;
    try {
      const response = await fetch(url, {
        headers: { Accept: "text/html" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`GET ${url} → ${response.status}`);
      if (response.redirected) throw new Error(`GET ${url} → ${response.url}`);
      const children = sectionFrom(await response.text(), this.id);
      if (children === null) throw new Error(`no #${this.id} in ${url}`);
      if (controller.signal.aborted) return;
      this.replaceChildren(...children);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      const id = reportClientError(
        "refreshing-section",
        String((error as Error)?.message ?? error),
        { toast: false },
      );
      window.toast(`This section didn't refresh (error ${id}) — reload the page`, "error");
    }
  }
}

customElements.define("refreshing-section", RefreshingSectionElement);
