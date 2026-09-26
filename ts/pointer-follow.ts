// One hover model for menus and pickers.
// A scroll repeats the position; skip it.
// `activate` must not scroll.
export function followPointer(
  container: HTMLElement,
  itemSelector: string,
  activate: (item: HTMLElement) => void,
): () => void {
  let lastX: number | null = null;
  let lastY: number | null = null;
  const onMove = (event: PointerEvent): void => {
    if (event.pointerType !== "mouse") return;
    if (event.clientX === lastX && event.clientY === lastY) return;
    lastX = event.clientX;
    lastY = event.clientY;
    const item = (event.target as Element).closest<HTMLElement>(itemSelector);
    if (item && container.contains(item)) activate(item);
  };
  container.addEventListener("pointermove", onMove);
  return () => container.removeEventListener("pointermove", onMove);
}
