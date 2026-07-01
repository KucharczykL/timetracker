import { describe, it, expect } from "vitest";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { MODIFIER_PHRASES, summarize, type SummaryContext } from "./summary.js";
import type { FieldMeta, GroupNode } from "./types.js";

// Minimal FieldMeta stub: only the fields summary reads.
function field(partial: Partial<FieldMeta> & { name: string }): FieldMeta {
  return {
    name: partial.name,
    label: partial.label ?? partial.name,
    kind: partial.kind ?? "string",
    nullable: partial.nullable ?? false,
    choices: partial.choices ?? [],
    modifiers: partial.modifiers ?? [],
    relations: partial.relations ?? [],
    search_url: partial.search_url ?? "",
    is_m2m: partial.is_m2m ?? false,
  };
}

const GAME: SummaryContext = {
  modelKey: "game",
  modelLabel: "Games",
  models: {
    game: {
      fields: new Map([
        ["name", field({ name: "name", label: "Name", kind: "string" })],
        [
          "status",
          field({
            name: "status",
            label: "Status",
            kind: "set",
            choices: [
              { value: "f", label: "Finished" },
              { value: "p", label: "Playing" },
            ],
          }),
        ],
      ]),
    },
  },
};

function root(...children: GroupNode["children"]): GroupNode {
  return { kind: "group", id: "g", connective: "AND", negate: false, children };
}

describe("summarize — frame + scalar leaf", () => {
  it("renders the empty root as the all-items frame", () => {
    expect(summarize(root(), GAME)).toBe("Games (all).");
  });

  it("renders a single choice-valued leaf with its label", () => {
    const tree = root({
      kind: "criterion",
      id: "c",
      field: "status",
      criterion: { value: ["f"], modifier: "INCLUDES" },
      negate: false,
    });
    expect(summarize(tree, GAME)).toBe("Games where Status is Finished.");
  });

  it("renders a leaf with no field chosen as a placeholder", () => {
    const tree = root({ kind: "criterion", id: "c", field: "", criterion: {}, negate: false });
    expect(summarize(tree, GAME)).toBe("Games where ….");
  });

  it("renders a field chosen but no value yet as label + placeholder", () => {
    const tree = root({
      kind: "criterion",
      id: "c",
      field: "name",
      criterion: {},
      negate: false,
    });
    expect(summarize(tree, GAME)).toBe("Games where Name ….");
  });
});

describe("summarize — modifier families", () => {
  const CTX: SummaryContext = {
    modelKey: "game",
    modelLabel: "Games",
    models: {
      game: {
        fields: new Map([
          ["name", field({ name: "name", label: "Name", kind: "string" })],
          ["playtime", field({ name: "playtime", label: "Playtime", kind: "number" })],
          ["mastered", field({ name: "mastered", label: "Mastered", kind: "bool" })],
        ]),
      },
    },
  };
  function one(field: string, criterion: Record<string, unknown>): string {
    return summarize(
      root({ kind: "criterion", id: "c", field, criterion, negate: false }),
      CTX,
    );
  }

  it("phrases NOT_EQUALS", () => {
    expect(one("name", { value: "zelda", modifier: "NOT_EQUALS" })).toBe(
      "Games where Name is not zelda.",
    );
  });
  it("phrases comparators", () => {
    expect(one("playtime", { value: "2", modifier: "GREATER_THAN_OR_EQUAL" })).toBe(
      "Games where Playtime is at least 2.",
    );
    expect(one("playtime", { value: "5", modifier: "LESS_THAN" })).toBe(
      "Games where Playtime is less than 5.",
    );
  });
  it("phrases BETWEEN with both bounds", () => {
    expect(one("playtime", { value: "2", value2: "5", modifier: "BETWEEN" })).toBe(
      "Games where Playtime is between 2 and 5.",
    );
  });
  it("phrases presence modifiers with no value", () => {
    expect(one("name", { modifier: "IS_NULL" })).toBe("Games where Name is empty.");
    expect(one("name", { modifier: "NOT_NULL" })).toBe("Games where Name is set.");
  });
  it("phrases regex modifiers", () => {
    expect(one("name", { value: "^z", modifier: "MATCHES_REGEX" })).toBe(
      "Games where Name matches ^z.",
    );
  });
  it("phrases a bool as yes/no", () => {
    expect(one("mastered", { value: true, modifier: "EQUALS" })).toBe(
      "Games where Mastered is yes.",
    );
    expect(one("mastered", { value: false, modifier: "EQUALS" })).toBe(
      "Games where Mastered is no.",
    );
  });
});

describe("summarize — set values", () => {
  const CTX: SummaryContext = {
    modelKey: "game",
    modelLabel: "Games",
    models: {
      game: {
        fields: new Map([
          [
            "status",
            field({
              name: "status",
              label: "Status",
              kind: "set",
              choices: [
                { value: "f", label: "Finished" },
                { value: "p", label: "Playing" },
                { value: "a", label: "Abandoned" },
              ],
            }),
          ],
          ["device", field({ name: "device", label: "Device", kind: "set" })],
        ]),
      },
    },
  };
  function one(field: string, criterion: Record<string, unknown>): string {
    return summarize(root({ kind: "criterion", id: "c", field, criterion, negate: false }), CTX);
  }

  it("phrases a single-value INCLUDES as 'is'", () => {
    expect(one("status", { value: ["f"], modifier: "INCLUDES" })).toBe(
      "Games where Status is Finished.",
    );
  });
  it("phrases a multi-value INCLUDES as 'is one of'", () => {
    expect(one("status", { value: ["f", "p"], modifier: "INCLUDES" })).toBe(
      "Games where Status is one of Finished or Playing.",
    );
  });
  it("phrases EXCLUDES", () => {
    expect(one("status", { value: ["a"], modifier: "EXCLUDES" })).toBe(
      "Games where Status is not Abandoned.",
    );
  });
  it("phrases INCLUDES_ALL and INCLUDES_ONLY", () => {
    expect(one("status", { value: ["f", "p"], modifier: "INCLUDES_ALL" })).toBe(
      "Games where Status has all of Finished and Playing.",
    );
    expect(one("status", { value: ["f", "p"], modifier: "INCLUDES_ONLY" })).toBe(
      "Games where Status is exactly Finished and Playing.",
    );
  });
  it("appends an excludes clause when both present (search-select {id,label} entries)", () => {
    expect(
      one("device", {
        value: [{ id: "1", label: "Steam Deck" }],
        excludes: [{ id: "2", label: "Switch" }],
        modifier: "INCLUDES",
      }),
    ).toBe("Games where Device is Steam Deck and not Switch.");
  });
  it("phrases an excludes-only set as 'is not'", () => {
    expect(
      one("device", { value: [], excludes: [{ id: "2", label: "Switch" }], modifier: "INCLUDES" }),
    ).toBe("Games where Device is not Switch.");
  });
});

describe("summarize — connectives, parens, NOT", () => {
  const CTX: SummaryContext = {
    modelKey: "game",
    modelLabel: "Games",
    models: {
      game: {
        fields: new Map([
          [
            "status",
            field({
              name: "status",
              label: "Status",
              kind: "set",
              choices: [
                { value: "f", label: "Finished" },
                { value: "p", label: "Playing" },
              ],
            }),
          ],
          [
            "platform",
            field({
              name: "platform",
              label: "Platform",
              kind: "set",
              choices: [
                { value: "pc", label: "PC" },
                { value: "sw", label: "Switch" },
              ],
            }),
          ],
        ]),
      },
    },
  };
  const finished = { kind: "criterion", id: "a", field: "status", criterion: { value: ["f"], modifier: "INCLUDES" }, negate: false } as const;
  const pc = { kind: "criterion", id: "b", field: "platform", criterion: { value: ["pc"], modifier: "INCLUDES" }, negate: false } as const;
  const sw = { kind: "criterion", id: "c", field: "platform", criterion: { value: ["sw"], modifier: "INCLUDES" }, negate: false } as const;

  it("joins two AND leaves", () => {
    expect(summarize(root(finished, pc), CTX)).toBe(
      "Games where Status is Finished and Platform is PC.",
    );
  });
  it("parenthesizes a differing-connective child group", () => {
    const orGroup: GroupNode = { kind: "group", id: "or", connective: "OR", negate: false, children: [pc, sw] };
    expect(summarize(root(finished, orGroup), CTX)).toBe(
      "Games where Status is Finished and (Platform is PC or Platform is Switch).",
    );
  });
  it("does not parenthesize a same-connective single-child group", () => {
    const andGroup: GroupNode = { kind: "group", id: "in", connective: "AND", negate: false, children: [pc] };
    expect(summarize(root(finished, andGroup), CTX)).toBe(
      "Games where Status is Finished and Platform is PC.",
    );
  });
  it("prefixes a negated leaf with not (…)", () => {
    expect(summarize(root({ ...finished, negate: true }), CTX)).toBe(
      "Games where not (Status is Finished).",
    );
  });
  it("prefixes a negated group with not (…)", () => {
    const orGroup: GroupNode = { kind: "group", id: "or", connective: "OR", negate: true, children: [pc, sw] };
    expect(summarize(root(orGroup), CTX)).toBe(
      "Games where not (Platform is PC or Platform is Switch).",
    );
  });
});

describe("summarize — relation descent", () => {
  const CTX: SummaryContext = {
    modelKey: "game",
    modelLabel: "Games",
    models: {
      game: {
        fields: new Map([
          [
            "session_filter",
            field({
              name: "session_filter",
              label: "Sessions",
              kind: "relation",
              relations: [{ field: "session_filter", filter: "SessionFilter", model: "Session" }],
            }),
          ],
        ]),
      },
      session: {
        fields: new Map([
          ["device", field({ name: "device", label: "Device", kind: "set" })],
        ]),
      },
    },
  };
  function relation(match: "ANY" | "NONE" | "ALL", childChildren: GroupNode["children"], negate = false): GroupNode {
    return root({
      kind: "relation",
      id: "r",
      field: "session_filter",
      match,
      negate,
      child: { kind: "group", id: "rc", connective: "AND", negate: false, children: childChildren },
    });
  }
  const deviceHandheld = { kind: "criterion", id: "d", field: "device", criterion: { value: [{ id: "1", label: "Handheld" }], modifier: "INCLUDES" }, negate: false } as const;

  it("phrases ANY with a child body under the target model", () => {
    expect(summarize(relation("ANY", [deviceHandheld]), CTX)).toBe(
      "Games where any sessions matching (Device is Handheld).",
    );
  });
  it("phrases NONE and ALL quantifiers", () => {
    expect(summarize(relation("NONE", [deviceHandheld]), CTX)).toBe(
      "Games where no sessions matching (Device is Handheld).",
    );
    expect(summarize(relation("ALL", [deviceHandheld]), CTX)).toBe(
      "Games where all sessions matching (Device is Handheld).",
    );
  });
  it("phrases an empty ANY child as a presence test", () => {
    expect(summarize(relation("ANY", []), CTX)).toBe(
      "Games where any related sessions.",
    );
  });
  it("phrases an empty NONE child as a no-related test", () => {
    expect(summarize(relation("NONE", []), CTX)).toBe(
      "Games where no related sessions.",
    );
  });
  it("phrases an empty ALL child as the vacuous match-all", () => {
    expect(summarize(relation("ALL", []), CTX)).toBe("Games where matches all.");
  });
  it("negates a relation descent", () => {
    expect(summarize(relation("ANY", [deviceHandheld], true), CTX)).toBe(
      "Games where not (any sessions matching (Device is Handheld)).",
    );
  });
  it("renders an unset relation field as a placeholder", () => {
    const tree = root({
      kind: "relation",
      id: "r",
      field: "",
      match: "ANY",
      negate: false,
      child: { kind: "group", id: "rc", connective: "AND", negate: false, children: [] },
    });
    expect(summarize(tree, CTX)).toBe("Games where ….");
  });
});

describe("summarize — field comparison", () => {
  const CTX: SummaryContext = {
    modelKey: "game",
    modelLabel: "Games",
    models: {
      game: {
        fields: new Map(),
        columns: new Map([
          ["year_released", "Release year"],
          ["original_year_released", "Original release year"],
        ]),
      },
    },
  };
  function comparison(payload: Record<string, unknown>): string {
    return summarize(
      root({ kind: "comparison", id: "cmp", comparison: payload, negate: false }),
      CTX,
    );
  }

  it("phrases a complete comparison with column labels", () => {
    expect(
      comparison({ left: "original_year_released", right: "year_released", modifier: "LESS_THAN" }),
    ).toBe("Games where Original release year is less than Release year.");
  });
  it("appends (by day) for date granularity", () => {
    expect(
      comparison({ left: "year_released", right: "original_year_released", modifier: "EQUALS", granularity: "date" }),
    ).toBe("Games where Release year is Original release year (by day).");
  });
  it("renders an incomplete comparison as a placeholder", () => {
    expect(comparison({ left: "year_released" })).toBe("Games where ….");
  });
});

describe("summary modifier contract artifact", () => {
  it("writes the canonical modifier list for the Python contract", () => {
    const keys = Object.keys(MODIFIER_PHRASES).sort();
    const canonicalPath = fileURLToPath(
      new URL("./summary-modifiers.canonical.json", import.meta.url),
    );
    writeFileSync(canonicalPath, JSON.stringify(keys, null, 2));
    expect(keys.length).toBeGreaterThan(0);
  });
});
