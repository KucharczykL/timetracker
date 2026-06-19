export {};

declare global {
  interface Window {
    fetchWithHtmxTriggers(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
    toast(message: string, type?: string): void;
    readSearchSelect(form: HTMLElement): void;
    applyFilterBar(event: Event): boolean;
    clearFilterBar(formId: string, filterInputId: string): void;
    toggleStringFilterInput(radio: HTMLInputElement): void;
    showPresetNameInput(): void;
    savePreset(formId: string, filterInputId: string, saveUrl: string): void;
  }
}
