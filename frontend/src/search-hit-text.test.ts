import { describe, expect, it } from "vitest";
import { itemLabel, renderLawDocument } from "./search-hit-text";
import type { LawDocument, LawSection, SearchHit } from "./api/search";

function section(overrides: Partial<LawSection>): LawSection {
  return {
    id: "section",
    law_id: "test-law",
    law_name: "テスト法",
    article_no: "1",
    paragraph_no: 1,
    item_no: null,
    caption: "",
    heading: "第一条",
    text: "本文。",
    url: "/l/test-law/a/1/1",
    path: "テスト法/1",
    ...overrides,
  };
}

function hit(overrides: Partial<SearchHit> = {}): SearchHit {
  return {
    file_id: "hit",
    law_id: "test-law",
    law_name: "テスト法",
    article_no: "1",
    paragraph_no: 1,
    item_no: null,
    path: "テスト法/1",
    line: 0,
    snippet: "本文。",
    snippet_text: "本文。",
    highlights: [],
    url: "/l/test-law/a/1/1",
    blocks: [],
    ...overrides,
  };
}

function parseDocument(sections: LawSection[], activeHit: SearchHit = hit()): Document {
  const html = renderLawDocument(
    {
      law_id: "test-law",
      law_name: "テスト法",
      sections,
    } satisfies LawDocument,
    activeHit
  );
  return new DOMParser().parseFromString(html, "text/html");
}

describe("itemLabel", () => {
  it("renders small numeric item labels as kanji numerals", () => {
    expect(itemLabel(1)).toBe("一");
    expect(itemLabel(10)).toBe("十");
    expect(itemLabel(11)).toBe("十一");
    expect(itemLabel(20)).toBe("二十");
    expect(itemLabel(99)).toBe("九十九");
    expect(itemLabel("2の2")).toBe("2の2");
    expect(itemLabel(100)).toBe("100");
  });
});

describe("renderLawDocument", () => {
  it("does not duplicate article wrappers when article_no already includes 条", () => {
    const doc = parseDocument([
      section({
        article_no: "第1条",
        heading: "",
      }),
    ]);

    expect(doc.querySelector(".article-title")?.textContent).toBe("第1条");
  });

  it("groups paragraph lead and item rows under one article and renders caption once", () => {
    const doc = parseDocument(
      [
        section({
          caption: "（目的）",
          text: "この法律は、目的を定める。",
        }),
        section({
          item_no: 1,
          caption: "（目的）",
          text: "第一号の本文。",
          url: "/l/test-law/a/1/1/1",
        }),
        section({
          paragraph_no: 2,
          caption: "（目的）",
          text: "第二項の本文。",
          url: "/l/test-law/a/1/2",
        }),
      ],
      hit({ article_no: "1", paragraph_no: 1, item_no: 1 })
    );

    expect(doc.querySelectorAll(".article")).toHaveLength(1);
    expect(doc.querySelectorAll(".article-caption")).toHaveLength(1);
    expect(doc.querySelector(".article-caption")?.textContent).toBe("（目的）");
    expect(doc.querySelectorAll(".paragraph")).toHaveLength(2);
    expect(doc.querySelector(".item-row .marker")?.textContent).toBe("一");
    expect(doc.querySelector("#section-1-1-1")?.classList.contains("active")).toBe(true);
  });

  it("does not collapse unrelated empty article_no sections into one article", () => {
    const doc = parseDocument([
      section({
        article_no: "",
        heading: "第一見出し",
        text: "第一本文。",
        url: "/l/test-law/a/missing-1",
        path: "テスト法/missing-1",
      }),
      section({
        article_no: "",
        heading: "第二見出し",
        text: "第二本文。",
        url: "/l/test-law/a/missing-2",
        path: "テスト法/missing-2",
      }),
    ]);

    expect(doc.querySelectorAll(".article")).toHaveLength(2);
  });
});
