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
