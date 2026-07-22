export {};

declare global {
  interface Window {
    dispatchHtmxTriggers(response: Response): void;
    fetchWithHtmxTriggers(
      input: RequestInfo | URL,
      init?: RequestInit,
      triggerDispatch?: "immediate" | "deferred",
    ): Promise<Response>;
    toast(message: string, type?: string): void;
  }
}
