import { describe, expect, it } from "vitest";
import { mergeHighlightRanges } from "./highlight-ranges";

describe("mergeHighlightRanges", () => {
  it("merges overlapping and adjacent ranges", () => {
    expect(
      mergeHighlightRanges(
        [
          { start: 4, end: 7 },
          { start: 1, end: 3 },
          { start: 3, end: 5 },
        ],
        10
      )
    ).toEqual([{ start: 1, end: 7 }]);
  });

  it("drops invalid ranges", () => {
    expect(
      mergeHighlightRanges(
        [
          { start: -1, end: 2 },
          { start: 2, end: 2 },
          { start: 2, end: 12 },
          { start: 2, end: 4 },
        ],
        5
      )
    ).toEqual([{ start: 2, end: 4 }]);
  });
});
