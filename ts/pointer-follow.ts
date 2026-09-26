// One hover model for menus and pickers.
//
// Only a real mouse move activates: a touch has no hover, and a list that
// scrolls under a still cursor reports a move at the same position.
// `activate` must not scroll, or the list creeps under the cursor.
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
