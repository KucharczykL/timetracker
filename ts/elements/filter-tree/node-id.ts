/**
 * Stable per-node identity for the filter tree (issue #192).
 *
 * Every `FilterNode` carries an `id` assigned at construction (factories +
 * deserialize). It is a client-only handle: the serializer never reads it, so it
 * never reaches the wire. `<filter-group>` keys its DOM reconciliation on it, so a
 * leaf's live value widget survives structural edits (add/remove/move/negate) that
 * rebuild the surrounding tree — the id follows the node through the immutable ops
 * (a `{...node}` spread copies it), so the same row element is reused.
 */
let counter = 0;

export function nextNodeId(): string {
  counter += 1;
  return `n${counter}`;
}

// Test seam: reset the monotonic counter so id sequences are reproducible.
export function resetNodeIds(): void {
  counter = 0;
}
