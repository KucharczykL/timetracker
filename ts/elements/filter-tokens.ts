/**
 * Behavioral filter-modifier tokens the TS widgets branch on (#152).
 *
 * These are NOT the filter vocabulary — that flows from the server as data
 * (data-kind, server-rendered modifier rows, the field-comparison `operators`
 * list). These are the handful of modifier tokens whose IDENTITY drives client
 * UI behavior, so they legitimately live in TS:
 *
 *   - PRESENCE_MODIFIERS: mutually exclusive with value pills (selecting one
 *     clears the pills, and adding a pill clears a presence modifier).
 *   - RANGE_MODIFIERS: reveal the second value input.
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
