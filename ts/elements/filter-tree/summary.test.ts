import { describe, it, expect } from "vitest";
import { summarize, type SummaryContext } from "./summary.js";
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
