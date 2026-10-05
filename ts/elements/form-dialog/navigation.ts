/** Leaving the page; tests replace it. */
export const browser = {
  assign(url: string): void {
    location.assign(url);
  },
  reload(): void {
    location.reload();
  },
};
