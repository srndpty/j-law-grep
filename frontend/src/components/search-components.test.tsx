import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SearchHit } from "../api/search";
import { SearchBar } from "./SearchBar";
import { SearchDietFilters } from "./SearchDietFilters";
import { SearchModeTabs } from "./SearchModeTabs";
import { SearchResultItem } from "./SearchResultItem";
import { SearchResultList } from "./SearchResultList";
import { Button } from "./ui/button";

vi.mock("../search-hit-text", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../search-hit-text")>();
  return {
    ...actual,
    openLawDocument: vi.fn(),
  };
});

import { openLawDocument } from "../search-hit-text";

const hit: SearchHit = {
  file_id: "1",
  law_id: "minpo",
  law_name: "民法",
  article_no: "709",
  paragraph_no: "1",
  item_no: null,
  path: "民法/709",
  line: 1,
  snippet: "故意又は過失",
  snippet_text: "故意又は過失",
  highlights: [{ start: 0, end: 2 }],
  url: "/laws/minpo?article=709",
  blocks: [],
};

describe("SearchBar", () => {
  it("reports typing and composition events", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onCompositionStart = vi.fn();
    const onCompositionEnd = vi.fn();
    render(
      <SearchBar
        value=""
        onChange={onChange}
        onCompositionStart={onCompositionStart}
        onCompositionEnd={onCompositionEnd}
      />
    );
    const input = screen.getByPlaceholderText("キーワードや法令条番号を入力");

    await user.type(input, "民");
    input.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true }));
    input.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true }));

    expect(onChange).toHaveBeenCalledWith("民");
    expect(onCompositionStart).toHaveBeenCalled();
    expect(onCompositionEnd).toHaveBeenCalled();
  });
});

describe("SearchModeTabs", () => {
  it("selects a mode", async () => {
    const onChange = vi.fn();
    render(<SearchModeTabs mode="auto" onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "Boolean" }));

    expect(onChange).toHaveBeenCalledWith("boolean");
  });
});

describe("SearchDietFilters", () => {
  it("renders only for diet-capable sources and reports changes", async () => {
    const onChange = vi.fn();
    const onClear = vi.fn();
    const { rerender } = render(
      <SearchDietFilters source="law" filters={{}} onChange={onChange} onClear={onClear} />
    );

    expect(screen.queryByLabelText("院")).not.toBeInTheDocument();

    rerender(
      <SearchDietFilters
        source="diet"
        filters={{ house: "", meeting: "", speaker: "", date_from: "", date_to: "" }}
        onChange={onChange}
        onClear={onClear}
      />
    );

    await userEvent.selectOptions(screen.getByLabelText("院"), "衆議院");
    await userEvent.type(screen.getByPlaceholderText("発言者（前方一致）"), "山田");
    await userEvent.click(screen.getByRole("button", { name: "クリア" }));

    expect(onChange).toHaveBeenCalledWith("house", "衆議院");
    expect(onChange).toHaveBeenCalledWith("speaker", "山");
    expect(onClear).toHaveBeenCalled();
    // 会期と質問/答弁の別は質問主意書だけの絞り込み。
    expect(screen.queryByLabelText("会期")).not.toBeInTheDocument();
  });

  it("swaps the diet-only and shuisho-only fields per source", async () => {
    const onChange = vi.fn();
    render(
      <SearchDietFilters source="shuisho" filters={{}} onChange={onChange} onClear={vi.fn()} />
    );

    expect(screen.queryByPlaceholderText("会議名")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("会期"), "217");
    await userEvent.selectOptions(screen.getByLabelText("質問/答弁"), "answer");

    expect(onChange).toHaveBeenCalledWith("session", "2");
    expect(onChange).toHaveBeenCalledWith("shuisho_kind", "answer");
    expect(screen.getByPlaceholderText("提出者（前方一致）")).toBeInTheDocument();
  });
});

describe("SearchResultList", () => {
  it("renders empty state when not loading", () => {
    render(
      <SearchResultList
        hits={[]}
        selectedIndex={0}
        isLoading={false}
        onSelect={vi.fn()}
        setItemRef={vi.fn()}
      />
    );

    expect(screen.getByText("検索結果がありません。")).toBeInTheDocument();
  });

  it("renders hits, highlights, selection, and open action", async () => {
    const onSelect = vi.fn();
    const setItemRef = vi.fn();
    render(
      <SearchResultList
        hits={[hit]}
        selectedIndex={0}
        isLoading={false}
        onSelect={onSelect}
        setItemRef={setItemRef}
      />
    );

    expect(screen.getByText("民法")).toBeInTheDocument();
    expect(screen.getByText("故意")).toBeInTheDocument();
    expect(screen.getByRole("article")).toHaveAttribute("aria-selected", "true");

    await userEvent.click(screen.getByRole("button", { name: "該当条を開く" }));

    expect(onSelect).toHaveBeenCalledWith(0);
    expect(openLawDocument).toHaveBeenCalledWith(hit);
    expect(setItemRef).toHaveBeenCalledWith(0, expect.any(HTMLElement));
  });
});

describe("SearchResultItem", () => {
  it("falls back to snippet and path labels", () => {
    render(
      <SearchResultItem
        hit={{ ...hit, law_name: "", article_no: "第709条", snippet_text: undefined }}
        selected={false}
        onSelect={vi.fn()}
        setRef={vi.fn()}
      />
    );

    expect(screen.getByText("民法/709")).toBeInTheDocument();
    expect(screen.getByText("第709条")).toBeInTheDocument();
  });

  it("renders diet metadata", () => {
    render(
      <SearchResultItem
        hit={{
          ...hit,
          source_type: "diet",
          law_name: "衆議院 本会議 第212回 第12号",
          article_no: "1",
          house: "衆議院",
          meeting_name: "本会議",
          date: "2023-12-13",
          speaker: "額賀福志郎",
          speaker_group: "自由民主党",
        }}
        selected={false}
        onSelect={vi.fn()}
        setRef={vi.fn()}
      />
    );

    expect(screen.getByText("国会")).toBeInTheDocument();
    expect(screen.getByText("発言1")).toBeInTheDocument();
    expect(screen.getByText("衆議院")).toBeInTheDocument();
    expect(screen.getByText("本会議")).toBeInTheDocument();
    expect(screen.getByText("2023-12-13")).toBeInTheDocument();
    expect(screen.getByText("発言者: 額賀福志郎")).toBeInTheDocument();
  });

  it("renders shuisho metadata and labels the answer body", () => {
    render(
      <SearchResultItem
        hit={{
          ...hit,
          source_type: "shuisho",
          law_name: "創薬力強化に関する質問主意書",
          article_no: "a2",
          shuisho_kind: "answer",
          shuisho_number: "1",
          house: "衆議院",
          session: "217",
          date: "2025-02-04",
          speaker: "内閣総理大臣 石破 茂",
          url: "https://www.shugiin.go.jp/internet/itdb_shitsumon.nsf/html/shitsumon/b217001.htm",
        }}
        selected={false}
        onSelect={vi.fn()}
        setRef={vi.fn()}
      />
    );

    expect(screen.getByText("質問主意書")).toBeInTheDocument();
    expect(screen.getByText("答弁 第2段落")).toBeInTheDocument();
    expect(screen.getByText("第217回")).toBeInTheDocument();
    expect(screen.getByText("第1号")).toBeInTheDocument();
    expect(screen.getByText("答弁者: 内閣総理大臣 石破 茂")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "答弁本文を開く" })).toBeInTheDocument();
  });
});

describe("Button", () => {
  it("renders variants and asChild", () => {
    const { rerender } = render(<Button variant="secondary">戻る</Button>);
    expect(screen.getByRole("button", { name: "戻る" })).toHaveClass("bg-white");

    rerender(
      <Button asChild>
        <a href="/search">検索</a>
      </Button>
    );
    expect(screen.getByRole("link", { name: "検索" })).toHaveAttribute("href", "/search");
  });
});
