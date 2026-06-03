import { describe, expect, it } from "vitest";
import { shouldAutoSearch } from "./search-behavior";

describe("shouldAutoSearch", () => {
  it("requires at least two non-space characters", () => {
    expect(shouldAutoSearch("不", "auto", false)).toBe(false);
    expect(shouldAutoSearch("不当", "auto", false)).toBe(true);
  });

  it("does not auto-search during IME composition", () => {
    expect(shouldAutoSearch("不当", "auto", true)).toBe(false);
  });

  it("does not auto-search regex mode", () => {
    expect(shouldAutoSearch("不当", "regex", false)).toBe(false);
  });
});
