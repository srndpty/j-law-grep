import { fetchLawDocument, type LawDocument, type LawSection, type SearchHit } from "./api/search";

export function deriveArticleNo(hit: SearchHit): string {
  if (hit.article_no) return hit.article_no;
  const urlMatch = hit.url.match(/\/a\/([^/]+)/);
  if (urlMatch) return urlMatch[1];
  const parts = hit.path.split("/");
  if (parts.length >= 2 && parts[1]) return parts[1];
  return "";
}

export function deriveParagraphNo(hit: SearchHit): number | string | null {
  if (hit.paragraph_no !== null && hit.paragraph_no !== undefined) return hit.paragraph_no;
  const match = hit.url.match(/\/a\/[^/]+\/(\d+)/);
  if (match) {
    const value = Number(match[1]);
    return Number.isNaN(value) ? null : value;
  }
  return null;
}

export function formatLocation(hit: SearchHit): string {
  const base = hit.law_name || hit.path;
  const segments: string[] = [];
  const articleNo = deriveArticleNo(hit);
  const paragraphNo = deriveParagraphNo(hit);
  if (articleNo) {
    segments.push(hit.source_type === "diet" ? `発言${articleNo}` : articleLabel(articleNo));
  }
  if (paragraphNo) segments.push(`${paragraphNo}項`);
  if (hit.item_no) segments.push(`${hit.item_no}号`);
  const position = segments.join(" ");
  if (base && position) return `${base} / ${position}`;
  return base || position || hit.path;
}

function blockText(block: Record<string, unknown>): string {
  for (const key of ["text", "html", "content"]) {
    const value = block[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

export function hitText(hit: SearchHit): string {
  const blockTexts = hit.blocks.map(blockText).filter(Boolean);
  if (blockTexts.length) return blockTexts.join("\n\n");
  return hit.snippet_text ?? hit.snippet;
}

export function itemLabel(itemNo: number | string | null): string {
  if (itemNo === null || itemNo === undefined || itemNo === "") return "";
  const value = String(itemNo);
  const numeric = Number(value);
  const digits = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"];
  if (!Number.isInteger(numeric) || numeric <= 0 || numeric >= 100) return value;
  if (numeric < 10) return digits[numeric];
  const tens = Math.floor(numeric / 10);
  const ones = numeric % 10;
  return `${tens === 1 ? "" : digits[tens]}十${digits[ones]}`;
}

function articleLabel(articleNo: string): string {
  if (!articleNo) return "";
  return articleNo.includes("条") ? articleNo : `第${articleNo}条`;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function targetId(hit: SearchHit): string {
  return sectionId({
    article_no: hit.article_no,
    paragraph_no: hit.paragraph_no,
    item_no: hit.item_no,
  });
}

function sectionId(section: Pick<LawSection, "article_no" | "paragraph_no" | "item_no">): string {
  return ["section", section.article_no || "", section.paragraph_no ?? "", section.item_no ?? ""]
    .map((part) => encodeURIComponent(String(part)))
    .join("-");
}

function articleGroupKey(section: LawSection, fallbackIndex: number): string {
  if (section.article_no) return `article:${section.article_no}`;
  if (section.heading) return `heading:${section.heading}`;
  if (section.path) return `path:${section.path}`;
  if (section.url) return `url:${section.url}`;
  return `section:${fallbackIndex}`;
}

interface ParagraphGroup {
  paragraphNo: number | string | null;
  sections: LawSection[];
}

interface ArticleGroup {
  articleNo: string;
  caption: string;
  heading: string;
  paragraphs: ParagraphGroup[];
}

function groupLawSections(sections: LawSection[]): ArticleGroup[] {
  const articles: ArticleGroup[] = [];
  const articleIndex = new Map<string, ArticleGroup>();

  for (const section of sections) {
    const articleKey = articleGroupKey(section, articles.length);
    let article = articleIndex.get(articleKey);
    if (!article) {
      article = {
        articleNo: section.article_no || "",
        caption: section.caption ?? "",
        heading: section.heading,
        paragraphs: [],
      };
      articleIndex.set(articleKey, article);
      articles.push(article);
    }
    if (!article.caption && section.caption) article.caption = section.caption;
    if (!article.heading && section.heading) article.heading = section.heading;

    const paragraphKey = section.paragraph_no ?? "";
    let paragraph = article.paragraphs.find(
      (candidate) => String(candidate.paragraphNo ?? "") === String(paragraphKey)
    );
    if (!paragraph) {
      paragraph = { paragraphNo: section.paragraph_no, sections: [] };
      article.paragraphs.push(paragraph);
    }
    paragraph.sections.push(section);
  }

  return articles;
}

export function renderLawDocument(document: LawDocument, hit: SearchHit): string {
  const activeId = targetId(hit);
  const articles = groupLawSections(document.sections)
    .map((article) => {
      const articleTitle = article.heading || articleLabel(article.articleNo);
      const paragraphs = article.paragraphs
        .map((paragraph, paragraphIndex) => {
          const rows = paragraph.sections
            .map((section, sectionIndex) => {
              const id = sectionId(section);
              const active = id === activeId;
              const isParagraphLead = !section.item_no;
              const marker = isParagraphLead
                ? paragraphIndex === 0 && sectionIndex === 0
                  ? ""
                  : escapeHtml(String(section.paragraph_no ?? ""))
                : escapeHtml(itemLabel(section.item_no));
              return `
                <div id="${id}" class="law-row ${active ? "active" : ""} ${
                  isParagraphLead ? "paragraph-lead" : "item-row"
                }">
                  <div class="marker">${marker}</div>
                  <p>${escapeHtml(section.text).replace(/\n/g, "<br>")}</p>
                </div>`;
            })
            .join("");
          return `<div class="paragraph">${rows}</div>`;
        })
        .join("");

      return `
        <article class="article">
          ${
            article.caption
              ? `<div class="article-caption">${escapeHtml(article.caption)}</div>`
              : ""
          }
          <div class="article-body">
            <div class="article-title">${escapeHtml(articleTitle)}</div>
            <div class="article-content">${paragraphs}</div>
          </div>
        </article>`;
    })
    .join("");

  return `<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>${escapeHtml(document.law_name || hit.law_name)}</title>
  <style>
    body {
      margin: 0;
      background: #111516;
      color: #f5f5f5;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Yu Gothic UI",
        "Meiryo", sans-serif;
      font-size: 16px;
      line-height: 1.6;
    }
    header {
      position: sticky;
      top: 0;
      background: #111516;
      color: #f5f5f5;
      padding: 8px 12px;
      border-bottom: 1px solid #343a3d;
      z-index: 1;
    }
    h1 {
      margin: 0;
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0;
    }
    main {
      max-width: none;
      margin: 0;
      padding: 0 12px 48px;
    }
    .article {
      padding: 4px 0 10px;
    }
    .article-caption {
      font-weight: 700;
      padding-left: 24px;
    }
    .article-body {
      display: grid;
      grid-template-columns: max-content minmax(0, 1fr);
      column-gap: 16px;
      align-items: start;
    }
    .article-title {
      font-weight: 700;
      white-space: nowrap;
    }
    .article-content {
      min-width: 0;
    }
    .paragraph {
      margin: 0;
    }
    .law-row {
      display: grid;
      grid-template-columns: 24px minmax(0, 1fr);
      column-gap: 8px;
      scroll-margin-top: 52px;
      padding: 1px 4px;
    }
    .paragraph:first-of-type .law-row:first-child {
      grid-template-columns: 0 minmax(0, 1fr);
      column-gap: 0;
    }
    .paragraph:not(:first-child) .law-row:first-child {
      grid-template-columns: 24px minmax(0, 1fr);
      column-gap: 8px;
    }
    .law-row.active {
      color: #111516;
    }
    .law-row.active p {
      background: #f59e0b;
      color: #111516;
      box-decoration-break: clone;
      -webkit-box-decoration-break: clone;
    }
    .marker {
      color: #e8eef2;
      font-weight: 700;
      text-align: right;
      white-space: nowrap;
    }
    .law-row.active .marker {
      color: #f5f5f5;
    }
    p {
      margin: 0;
      min-width: 0;
      white-space: normal;
      overflow-wrap: anywhere;
    }
    @media (max-width: 640px) {
      body {
        font-size: 15px;
      }
      header {
        padding: 8px 10px;
      }
      main {
        padding: 0 8px 40px;
      }
      .article-title {
        margin: 4px 0 0;
      }
      .article-body {
        display: block;
      }
      .paragraph:first-of-type .law-row:first-child {
        grid-template-columns: 24px minmax(0, 1fr);
        column-gap: 8px;
      }
    }
  </style>
</head>
<body>
  <header><h1>${escapeHtml(document.law_name || hit.law_name)}</h1></header>
  <main>${articles}</main>
  <script>
    document.getElementById(${JSON.stringify(activeId)})?.scrollIntoView({ block: "center" });
  </script>
</body>
</html>`;
}

function writeLoading(tab: Window, hit: SearchHit) {
  tab.document.open();
  tab.document.write(
    `<!doctype html><meta charset="utf-8"><title>${escapeHtml(
      hit.law_name || "読み込み中"
    )}</title><body style="font-family: sans-serif; padding: 24px;">読み込み中...</body>`
  );
  tab.document.close();
}

function writeError(tab: Window, message: string) {
  tab.document.open();
  tab.document.write(`<!doctype html><meta charset="utf-8"><title>読み込みエラー</title>
    <body style="font-family: sans-serif; padding: 24px;">
      <h1>法律全文を開けませんでした</h1>
      <p>${escapeHtml(message)}</p>
    </body>`);
  tab.document.close();
}

export async function openLawDocument(hit: SearchHit) {
  if (hit.source_type === "diet" && hit.url) {
    window.open(hit.url, "_blank", "noopener");
    return;
  }
  const tab = window.open("about:blank", "_blank");
  if (!tab) return;
  tab.opener = null;
  writeLoading(tab, hit);
  try {
    if (!hit.law_id) throw new Error("検索結果に law_id が含まれていません。");
    const document = await fetchLawDocument(hit.law_id, deriveArticleNo(hit));
    tab.document.open();
    tab.document.write(renderLawDocument(document, hit));
    tab.document.close();
  } catch (err) {
    writeError(tab, err instanceof Error ? err.message : "不明なエラーです。");
  }
}
