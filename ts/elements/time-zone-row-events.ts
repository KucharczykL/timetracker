/** The `time-zone-row:change` contract, in its own module so neither
 * `time-zone-row.ts` nor `date-time-field.ts` has to import the other's full
 * module (which would invert their `customElements.define` order — whichever
 * module a browser evaluates first upgrades first, and an already-upgraded
 * row can announce before an unregistered field has a listener). */
export const TIME_ZONE_ROW_CHANGE_EVENT = "time-zone-row:change";

export interface TimeZoneRowChangeDetail {
  fieldName: string; // the zone field, e.g. "timestamp_start_timezone"
  zone: string; // the effective zone the row now means (never "")
}
