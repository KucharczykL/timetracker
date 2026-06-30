/**
 * Behavioral filter-modifier tokens the TS widgets branch on (#152).
 *
 * These are NOT the filter vocabulary — that flows from the server as data
 * (data-kind, server-rendered modifier rows, the field-comparison `operators`
 * list). These are the handful of modifier tokens whose IDENTITY drives client
 * UI behavior, so they legitimately live in TS:
 *
 *   - PRESENCE_MODIFIERS: in the set widget, mutually exclusive with value pills
 *     (selecting one clears the pills, and adding a pill clears a presence
 *     modifier); in the string/number widgets, serialize to a value-less
 *     `{ modifier }` criterion (no value/value2).
 *   - RANGE_MODIFIERS: signal that a second bound (value2) is present and must be
 *     read and serialized from the number widget's second input.
 *
 * The single TS home for these tokens. `tests/test_filter_tokens_contract.py`
 * asserts every value here is a real `common.criteria.Modifier`, so a renamed or
 * removed Python modifier fails CI instead of silently orphaning a literal (the
 * #141 failure mode).
 */

export const PRESENCE_MODIFIERS = ["IS_NULL", "NOT_NULL"] as const;
export const RANGE_MODIFIERS = ["BETWEEN", "NOT_BETWEEN"] as const;

export function isPresenceModifier(modifier: string): boolean {
  return (PRESENCE_MODIFIERS as readonly string[]).includes(modifier);
}

export function isRangeModifier(modifier: string): boolean {
  return (RANGE_MODIFIERS as readonly string[]).includes(modifier);
}
