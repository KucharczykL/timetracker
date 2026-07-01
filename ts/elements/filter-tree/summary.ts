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
  ComparisonLeaf,
  CriterionLeaf,
  FieldMeta,
  FilterNode,
  GroupNode,
  RelationMatch,
  RelationNode,
} from "./types.js";
import { isComparisonComplete, isCriterionComplete } from "./operations.js";
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
    .map((child) => renderChildForGroup(child, node.connective, model, ctx))
    .filter((part) => part.length > 0);
  return parts.join(` ${word} `);
}

// A child rendered for placement inside a group: wrap a non-negated nested group in
// parens when it has >1 child or a connective differing from its parent's (a
// negated group already parenthesizes itself via renderNode).
function renderChildForGroup(
  child: FilterNode,
  parentConnective: GroupNode["connective"],
  model: SummaryModel | undefined,
  ctx: SummaryContext,
): string {
  const rendered = renderNode(child, model, ctx);
  if (child.kind === "group" && !child.negate && rendered.length > 0) {
    const needsParens = child.children.length > 1 || child.connective !== parentConnective;
    if (needsParens) return `(${rendered})`;
  }
  return rendered;
}

function renderNode(node: FilterNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  const inner = renderInner(node, model, ctx);
  if (!inner) return "";
  return node.negate ? `not (${inner})` : inner;
}

function renderInner(node: FilterNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  switch (node.kind) {
    case "group":
      return joinChildren(node, model, ctx);
    case "criterion":
      return renderCriterion(node, model);
    case "relation":
      return renderRelation(node, model, ctx);
    case "comparison":
      return renderComparison(node, model);
    default:
      return "";
  }
}

function renderComparison(leaf: ComparisonLeaf, model: SummaryModel | undefined): string {
  if (!isComparisonComplete(leaf)) return PLACEHOLDER;
  const { left, right, modifier, granularity } = leaf.comparison;
  const leftLabel = model?.columns?.get(left as string) ?? String(left);
  const rightLabel = model?.columns?.get(right as string) ?? String(right);
  const phrase = MODIFIER_PHRASES[modifier as string] ?? String(modifier);
  const suffix = granularity === "date" ? " (by day)" : "";
  return `${leftLabel} ${phrase} ${rightLabel}${suffix}`;
}

// "all" (not "every") so the quantifier agrees with the plural, as-is relation
// label: "all sessions" / "any sessions" / "no sessions" all read grammatically.
const QUANTIFIERS: Record<RelationMatch, string> = { ANY: "any", NONE: "no", ALL: "all" };

// The relation clause uses "matching (…)" rather than an inner "where": the frame is
// already "<Model> where …", so a nested "where" would collide. "matching (…)" reads
// cleanly after the frame's "where" and after a joining "and".
function renderRelation(node: RelationNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  if (!node.field) return PLACEHOLDER; // no field → target model unknown, don't guess a body
  const meta = model?.fields.get(node.field);
  const noun = (meta?.label ?? node.field).toLowerCase();
  const targetKey = targetModelKey(meta, ctx);
  const targetModel = ctx.models[targetKey];
  const body = node.child.children.length ? joinChildren(node.child, targetModel, ctx) : "";
  if (!body) return emptyRelationPhrase(node.match, noun);
  return `${QUANTIFIERS[node.match]} ${noun} matching (${body})`;
}

// The model key a relation descends into — its RelationTarget.model lower-cased,
// mirroring filter-group's targetModel. Falls back to the root when unknown.
function targetModelKey(meta: FieldMeta | undefined, ctx: SummaryContext): string {
  return meta?.relations[0]?.model?.toLowerCase() ?? ctx.modelKey;
}

// What an empty relation child matches, per quantifier — the presence test (#225),
// model-agnostic beyond the relation noun. ALL over an empty child is vacuously true.
function emptyRelationPhrase(match: RelationMatch, noun: string): string {
  switch (match) {
    case "ANY":
      return `any related ${noun}`;
    case "NONE":
      return `no related ${noun}`;
    case "ALL":
      return "matches all";
  }
  const unreachable: never = match;
  return unreachable;
}

function renderCriterion(leaf: CriterionLeaf, model: SummaryModel | undefined): string {
  if (!leaf.field) return PLACEHOLDER;
  const meta = model?.fields.get(leaf.field);
  const label = meta?.label ?? leaf.field;
  const modifier = String(leaf.criterion["modifier"] ?? "");
  // Sets gate on include-OR-exclude presence, not isCriterionComplete (which only
  // inspects `value` and would call an excludes-only set incomplete).
  if (meta?.kind === "set") {
    if (!setHasSelection(leaf.criterion, modifier)) return `${label} ${PLACEHOLDER}`;
    if (isPresenceModifier(modifier)) return `${label} ${MODIFIER_PHRASES[modifier] ?? modifier}`;
    return `${label} ${renderSet(leaf.criterion, meta, modifier)}`;
  }
  if (!isCriterionComplete(leaf)) return `${label} ${PLACEHOLDER}`;
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

// A set is worth rendering once it has a modifier and any selection (included,
// excluded, or a presence test). Mirrors buildSetCriterion's "included OR excluded"
// non-null condition rather than isCriterionComplete's value-only check.
function setHasSelection(criterion: CriterionLeaf["criterion"], modifier: string): boolean {
  if (!modifier) return false;
  if (isPresenceModifier(modifier)) return true;
  const value = criterion["value"];
  const excludes = criterion["excludes"];
  return (
    (Array.isArray(value) && value.length > 0) ||
    (Array.isArray(excludes) && excludes.length > 0)
  );
}

// Render a set criterion's predicate (everything after the field label): the
// included values phrased per modifier, with an appended "and not …" for excludes.
// *_ALL/_ONLY join with "and" (all required); INCLUDES/EXCLUDES join with "or".
function renderSet(
  criterion: CriterionLeaf["criterion"],
  meta: FieldMeta,
  modifier: string,
): string {
  const conjunction = modifier === "INCLUDES_ALL" || modifier === "INCLUDES_ONLY" ? "and" : "or";
  const included = renderList(criterion["value"], meta, conjunction);
  const excluded = renderList(criterion["excludes"], meta, "or");
  const clauses: string[] = [];
  if (included.items.length) {
    clauses.push(`${includePhrase(modifier, included.items.length)} ${included.text}`);
  }
  if (excluded.items.length) {
    // "is not X" on its own when there is no include clause; else "and not X".
    clauses.push(clauses.length ? `and not ${excluded.text}` : `is not ${excluded.text}`);
  }
  return clauses.join(" ");
}

// The verb for an included list: INCLUDES → is / is one of; the *_ALL/_ONLY forms
// keep their MODIFIER_PHRASES phrasing; EXCLUDES on the include slot → is not / is none of.
function includePhrase(modifier: string, count: number): string {
  if (modifier === "INCLUDES") return count > 1 ? "is one of" : "is";
  if (modifier === "EXCLUDES") return count > 1 ? "is none of" : "is not";
  return MODIFIER_PHRASES[modifier] ?? modifier;
}

interface RenderedList {
  items: string[];
  text: string; // items joined "a, b <conjunction> c"
}

function renderList(value: unknown, meta: FieldMeta, conjunction: string): RenderedList {
  const raw = Array.isArray(value) ? value : value == null ? [] : [value];
  const items = raw.map((item) => renderItem(item, meta));
  return { items, text: joinWords(items, conjunction) };
}

// Join a display list: "a", "a and b", "a, b or c" — final conjunction chosen by
// the caller ("or" for a disjunction of allowed values, "and" for required sets).
function joinWords(items: string[], conjunction: string): string {
  if (items.length <= 1) return items.join("");
  if (items.length === 2) return `${items[0]} ${conjunction} ${items[1]}`;
  return `${items.slice(0, -1).join(", ")} ${conjunction} ${items[items.length - 1]}`;
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
