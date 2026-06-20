export {};

declare global {
  interface Window {
    fetchWithHtmxTriggers(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
    toast(message: string, type?: string): void;
    readSearchSelect(form: HTMLElement): void;
  }
}
