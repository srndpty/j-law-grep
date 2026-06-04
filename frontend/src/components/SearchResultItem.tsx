import { Fragment } from "react";
import { clsx } from "clsx";
import { mergeHighlightRanges } from "../highlight-ranges";
import {
  deriveArticleNo,
  deriveParagraphNo,
  formatLocation,
  hitText,
  openLawDocument,
} from "../search-hit-text";
import type { SearchHit } from "../api/search";

function renderSnippet(hit: SearchHit): JSX.Element[] | string {
  const text = hit.snippet_text ?? hit.snippet;
  const highlights = mergeHighlightRanges(hit.highlights ?? [], text.length);
  if (!highlights.length) return text;

  const nodes: JSX.Element[] = [];
  let cursor = 0;
  highlights.forEach((range, index) => {
    if (range.start > cursor) {
      nodes.push(<Fragment key={`text-${index}`}>{text.slice(cursor, range.start)}</Fragment>);
    }
    nodes.push(<mark key={`mark-${index}`}>{text.slice(range.start, range.end)}</mark>);
    cursor = range.end;
  });
  if (cursor < text.length) {
    nodes.push(<Fragment key="tail">{text.slice(cursor)}</Fragment>);
  }
  return nodes;
}

function articleLabel(articleNo: string): string {
  return articleNo.includes("条") ? articleNo : `第${articleNo}条`;
}

interface Props {
  hit: SearchHit;
  selected: boolean;
  onSelect: () => void;
  setRef: (element: HTMLElement | null) => void;
}

export function SearchResultItem({ hit, selected, onSelect, setRef }: Props) {
  const previewText = hitText(hit);
  const articleNo = deriveArticleNo(hit);
  const paragraphNo = deriveParagraphNo(hit);

  return (
    <article
      ref={setRef}
      onClick={() => {
        onSelect();
      }}
      aria-selected={selected}
      className={clsx(
        "group relative cursor-default rounded-lg border bg-white p-4 shadow-sm transition hover:border-blue-400 hover:bg-blue-50/30 focus:outline-none focus:ring-2 focus:ring-blue-500",
        selected ? "border-blue-500 ring-1 ring-blue-500" : "border-gray-200"
      )}
      tabIndex={0}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <span className="font-semibold text-gray-700">{hit.law_name || hit.path}</span>
        {articleNo && (
          <span className="rounded border border-gray-200 px-1.5 py-0.5">
            {articleLabel(articleNo)}
          </span>
        )}
        {paragraphNo && (
          <span className="rounded border border-gray-200 px-1.5 py-0.5">{paragraphNo}項</span>
        )}
        {hit.item_no && (
          <span className="rounded border border-gray-200 px-1.5 py-0.5">{hit.item_no}号</span>
        )}
      </div>
      <div className="mt-2 text-sm leading-relaxed text-gray-900">{renderSnippet(hit)}</div>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onSelect();
          void openLawDocument(hit);
        }}
        className="mt-3 rounded border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-700 hover:border-blue-400 hover:text-blue-700"
      >
        該当条を開く
      </button>
      <div className="pointer-events-none absolute right-3 top-3 z-20 hidden w-96 max-w-[calc(100vw-3rem)] rounded-md border border-gray-300 bg-white p-3 text-xs leading-relaxed text-gray-800 shadow-lg group-hover:block group-focus:block">
        <div className="mb-2 border-b border-gray-200 pb-2 font-semibold text-gray-700">
          {formatLocation(hit)}
        </div>
        <div className="max-h-64 whitespace-pre-wrap overflow-auto">{previewText}</div>
      </div>
    </article>
  );
}
