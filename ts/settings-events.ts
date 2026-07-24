import {
  SETTING_NAMESPACES,
  SETTING_SOURCES,
  type SettingNamespace,
  type SettingSource,
} from "./generated/settings-vocabulary.js";

export type { SettingNamespace, SettingSource };
export { SETTING_SOURCES };

export type SettingValue = string | number | boolean | null;

/**
 * A committed setting's full resolved state. Two axes commonly get confused
 * because they share the string "user": `source` is WHERE the resolved value
 * came from (env/database/user/default) — a property of the *value*.
 * `namespace` is WHICH mutation surface (the personal settings page or the
 * site-admin page) emitted this event — a property of the *command that ran*.
 * They are independent: a personal preference CLEAR that falls through to an
 * env-shadowed value reports `source: "env"` while `namespace` stays `"user"`,
 * because a user-scoped command still executed it. (A third, unrelated axis —
 * the registry's SettingScope, whether a *key* is user- or site-scoped — never
 * appears in this payload at all.)
 *
 * Listener contract: match BOTH `key` and `namespace` before reacting to a
 * committed event. Matching `key` alone was sufficient before namespace
 * existed and is no longer safe — a badge or coordinator that only checks
 * `key` could react to the wrong page's mutation.
 *
 * Adding a third namespace: extend `SETTING_NAMESPACE_CHOICES` in
 * `timetracker/settings_commands.py`, update every `_setting_out` call site
 * in `games/api.py` to pass an explicit namespace literal, and update every
 * listener explicitly — there is no wildcard/catch-all listening mode.
 */
export interface ResolvedSetting {
  key: string;
  value: SettingValue;
  source: SettingSource;
  locked: boolean;
  namespace: SettingNamespace;
}

export const SETTING_COMMITTED_EVENT = "setting-committed" as const;

function isSettingValue(value: unknown): value is SettingValue {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

export function parseResolvedSetting(value: unknown): ResolvedSetting {
  if (typeof value !== "object" || value === null) {
    throw new Error("Invalid resolved setting response");
  }
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.key !== "string" ||
    candidate.key.length === 0 ||
    !isSettingValue(candidate.value) ||
    !SETTING_SOURCES.includes(candidate.source as SettingSource) ||
    typeof candidate.locked !== "boolean" ||
    !SETTING_NAMESPACES.includes(candidate.namespace as SettingNamespace)
  ) {
    throw new Error("Invalid resolved setting response");
  }
  return {
    key: candidate.key,
    value: candidate.value,
    source: candidate.source as SettingSource,
    locked: candidate.locked,
    namespace: candidate.namespace as SettingNamespace,
  };
}

export function dispatchSettingCommitted(value: unknown): ResolvedSetting {
  const resolved = parseResolvedSetting(value);
  document.body.dispatchEvent(
    new CustomEvent<ResolvedSetting>(SETTING_COMMITTED_EVENT, {
      detail: resolved,
      bubbles: true,
    }),
  );
  return resolved;
}

