import { Fragment } from "react";
import { ExternalLink } from "lucide-react";
import { clsx } from "clsx";
import { mergeHighlightRanges } from "../highlight-ranges";
import type { SearchHit } from "../api/search";

function deriveArticleNo(hit: SearchHit): string {
  if (hit.article_no) return hit.article_no;
  const urlMatch = hit.url.match(/\/a\/([^/]+)/);
  if (urlMatch) return urlMatch[1];
  const parts = hit.path.split("/");
  if (parts.length >= 2 && parts[1]) return parts[1];
  return "";
}

function deriveParagraphNo(hit: SearchHit): number | string | null {
  if (hit.paragraph_no !== null && hit.paragraph_no !== undefined) return hit.paragraph_no;
  const match = hit.url.match(/\/a\/[^/]+\/(\d+)/);
  if (match) {
    const value = Number(match[1]);
    return Number.isNaN(value) ? null : value;
  }
  return null;
}

function formatLocation(hit: SearchHit): string {
  const base = hit.law_name || hit.path;
  const segments: string[] = [];
  const articleNo = deriveArticleNo(hit);
  const paragraphNo = deriveParagraphNo(hit);
  if (articleNo) {
    segments.push(articleNo.includes("条") ? articleNo : `第${articleNo}条`);
  }
  if (paragraphNo) segments.push(`${paragraphNo}項`);
  if (hit.item_no) segments.push(`${hit.item_no}号`);
  const position = segments.join(" ");
  if (base && position) return `${base} / ${position}`;
  return base || position || hit.path;
}

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

interface Props {
  hit: SearchHit;
  selected: boolean;
  onSelect: () => void;
  setRef: (element: HTMLElement | null) => void;
}

export function SearchResultItem({ hit, selected, onSelect, setRef }: Props) {
  return (
    <article
      ref={setRef}
      onClick={onSelect}
      className={clsx(
        "rounded-lg border bg-white p-4 shadow-sm",
        selected ? "border-blue-500 ring-1 ring-blue-500" : "border-gray-200"
      )}
    >
      <div className="text-xs uppercase tracking-wide text-gray-500">{formatLocation(hit)}</div>
      <div className="mt-2 text-sm leading-relaxed text-gray-900">{renderSnippet(hit)}</div>
      {hit.url && (
        <a
          href={hit.url}
          className="mt-3 inline-flex items-center gap-1 text-sm text-blue-600 hover:underline"
        >
          パーマリンク
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      )}
    </article>
  );
}
