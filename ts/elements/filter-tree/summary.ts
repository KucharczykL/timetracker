/**
 * Natural-language filter summary (issue #194, phase 2c component 7 of #168).
 *
 * A pure, DOM-free tree → English walker: `summarize(tree, ctx)` turns a
 * `GroupNode` filter tree into a read-only sentence, recomputed by the builder on
 * every edit. Reads node payloads + explicit per-model `FieldMeta` metadata only;
 * the caller passes a *filled* tree (leaf payloads already read from live widgets —
 * see filter-group's fillCriteria). Mounting is component 10; this module is
 * standalone and fixture-tested, mirroring serializer.ts.
 */
import type {
  CriterionLeaf,
  FieldMeta,
  FilterNode,
  GroupNode,
} from "./types.js";
import { isCriterionComplete } from "./operations.js";
import { isPresenceModifier, isRangeModifier } from "../filter-tokens.js";

export interface SummaryModel {
  fields: Map<string, FieldMeta>;
  // Comparison column value -> label (issue #246 leaf); optional — only models that
  // admit a field comparison supply it.
  columns?: Map<string, string>;
}

export interface SummaryContext {
  modelKey: string; // root model key, e.g. "game"
  modelLabel: string; // root display noun, e.g. "Games"
  models: Record<string, SummaryModel>; // every reachable model key -> its metadata
}

// modifier token -> natural phrase. The SINGLE source the Python contract validates
// (Task 7): every key must be a real common.criteria.Modifier value.
export const MODIFIER_PHRASES: Record<string, string> = {
  EQUALS: "is",
  NOT_EQUALS: "is not",
  GREATER_THAN: "is more than",
  LESS_THAN: "is less than",
  GREATER_THAN_OR_EQUAL: "is at least",
  LESS_THAN_OR_EQUAL: "is at most",
  BETWEEN: "is between",
  NOT_BETWEEN: "is not between",
  IS_NULL: "is empty",
  NOT_NULL: "is set",
  MATCHES_REGEX: "matches",
  NOT_MATCHES_REGEX: "does not match",
  INCLUDES: "is",
  EXCLUDES: "is not",
  INCLUDES_ALL: "has all of",
  INCLUDES_ONLY: "is exactly",
};

const PLACEHOLDER = "…";

export function summarize(tree: GroupNode, ctx: SummaryContext): string {
  const model = ctx.models[ctx.modelKey];
  const body = tree.children.length ? joinChildren(tree, model, ctx) : "";
  if (!body) return `${ctx.modelLabel} (all).`;
  return `${ctx.modelLabel} where ${body}.`;
}

// Join a group's children with the group's connective word. Empty renders (empty
// nested groups) drop out.
function joinChildren(node: GroupNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  const word = node.connective === "AND" ? "and" : "or";
  const parts = node.children
    .map((child) => renderNode(child, model, ctx))
    .filter((part) => part.length > 0);
  return parts.join(` ${word} `);
}

function renderNode(node: FilterNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  switch (node.kind) {
    case "group":
      return joinChildren(node, model, ctx);
    case "criterion":
      return renderCriterion(node, model);
    default:
      return ""; // comparison + relation handled in later tasks
  }
}

function renderCriterion(leaf: CriterionLeaf, model: SummaryModel | undefined): string {
  if (!leaf.field) return PLACEHOLDER;
  const meta = model?.fields.get(leaf.field);
  const label = meta?.label ?? leaf.field;
  if (!isCriterionComplete(leaf)) return `${label} ${PLACEHOLDER}`;
  const modifier = String(leaf.criterion["modifier"]);
  const phrase = MODIFIER_PHRASES[modifier] ?? modifier;
  // Presence modifiers carry no value: the phrase ("is empty"/"is set") is the whole clause.
  if (isPresenceModifier(modifier)) return `${label} ${phrase}`;
  if (meta?.kind === "bool") {
    return `${label} ${phrase} ${renderBool(leaf.criterion["value"], meta)}`;
  }
  if (isRangeModifier(modifier)) {
    const lower = renderItem(leaf.criterion["value"], meta);
    const upper = renderItem(leaf.criterion["value2"], meta);
    return `${label} ${phrase} ${lower} and ${upper}`;
  }
  return `${label} ${phrase} ${renderValue(leaf.criterion["value"], meta)}`;
}

// A bool value's display: the field's matching choice label if present, else yes/no.
// Accept both the JS boolean the live widget emits and a "true"/"false" string (the
// deserialized shape), so a stringified true never renders "no".
function renderBool(value: unknown, meta: FieldMeta | undefined): string {
  const raw = String(value);
  const choice = meta?.choices.find((candidate) => candidate.value === raw);
  if (choice) return choice.label;
  return value === true || raw === "true" ? "yes" : "no";
}

// Render one stored value to its display form: a choice value maps to its label; a
// {label} object (search-select set entry) uses its label; otherwise the value's
// string form. Arrays render their first item here — multi-value phrasing arrives
// with the set/list tasks.
function renderValue(value: unknown, meta: FieldMeta | undefined): string {
  const first = Array.isArray(value) ? value[0] : value;
  return renderItem(first, meta);
}

function renderItem(item: unknown, meta: FieldMeta | undefined): string {
  if (item && typeof item === "object" && "label" in item) {
    return String((item as { label: unknown }).label);
  }
  const raw = String(item);
  const choice = meta?.choices.find((candidate) => candidate.value === raw);
  return choice ? choice.label : raw;
}
