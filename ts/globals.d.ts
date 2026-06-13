export {};

declare global {
  interface Window {
    fetchWithHtmxTriggers(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
  }
}
