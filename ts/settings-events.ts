export type SettingValue = string | number | boolean | null;

export const SETTING_SOURCES = [
  "user",
  "env_file",
  "env",
  "dotenv",
  "ini",
  "database",
  "default",
] as const;
export type SettingSource = typeof SETTING_SOURCES[number];

export interface ResolvedSetting {
  key: string;
  value: SettingValue;
  source: SettingSource;
  locked: boolean;
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
    typeof candidate.locked !== "boolean"
  ) {
    throw new Error("Invalid resolved setting response");
  }
  return {
    key: candidate.key,
    value: candidate.value,
    source: candidate.source as SettingSource,
    locked: candidate.locked,
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

