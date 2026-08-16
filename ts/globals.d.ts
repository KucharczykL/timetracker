export {};

declare global {
  interface Window {
    dispatchHtmxTriggers(response: Response): void;
    fetchWithHtmxTriggers(
      input: RequestInfo | URL,
      init?: RequestInit,
      triggerDispatch?: "immediate" | "deferred",
    ): Promise<Response>;
    toast(
      message: string,
      type?: string,
      options?: { id?: number | string; duration?: number | null },
    ): void;
    removeToast(id: number | string): void;
  }
}
